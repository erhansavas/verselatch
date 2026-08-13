#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import faulthandler
import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading

from logging.handlers import RotatingFileHandler
from pathlib import Path

from verselatch_core import (
    MAX_LYRICS_BYTES,
    AnalysisCancelled,
    VerseLatchError,
    same_lyric_text,
    align_lyrics,
    assess_generated_draft,
    is_non_lyric_asr_text,
    normalize,
    parse_lyric_document,
    parse_reviewed_lrc,
    parse_whisper_json,
    render_lrc,
    sanitize_generated_segments,
    timing_pattern_is_suspicious,
    validate_asr_segments,
)
from verselatch_core.storage import (
    open_regular_readonly,
    regular_file_state,
    file_state_tuple,
    require_regular_file_state,
    safe_read_text,
    safe_write_lrc,
    safe_write_reviewed_lrc,
)
from verselatch_core.process import (
    UNSAFE_NATIVE_ENV_KEYS,
    native_tool_env,
    terminate_process_group,
)
from verselatch_core.rhythm import (
    parse_aubio_times,
    rhythm_report_lines,
    summarize_rhythm,
)


def _ensure_private_directory(path: Path) -> None:
    """Create/validate an app-owned directory without following its leaf."""
    path.mkdir(
        mode=0o700,
        parents=True,
        exist_ok=True,
    )

    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise OSError(
            f"Refusing unsafe application directory: {path}"
        )

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise OSError(
                f"Refusing non-directory application path: {path}"
            )
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def _is_safe_private_directory(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
    )


class NoFollowRotatingFileHandler(RotatingFileHandler):
    """Rotating log handler that never follows the active log path."""

    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK

        descriptor = os.open(
            self.baseFilename,
            flags,
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError(
                    "Application log path is not a regular file."
                )
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(
                descriptor,
                self.mode,
                encoding=self.encoding,
                errors=self.errors,
            )
            descriptor = -1
            return stream
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def _xdg_base_directory(name: str, fallback: Path) -> Path:
    """Return an absolute XDG base directory or the specification fallback."""
    raw = os.environ.get(name, "")
    if raw:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
    return fallback


_HOME = Path.home()
if not _HOME.is_absolute():
    raise RuntimeError("VerseLatch requires an absolute home directory.")

_STATE_HOME = _xdg_base_directory(
    "XDG_STATE_HOME",
    _HOME / ".local" / "state",
)
_CONFIG_HOME = _xdg_base_directory(
    "XDG_CONFIG_HOME",
    _HOME / ".config",
)
_CACHE_HOME = _xdg_base_directory(
    "XDG_CACHE_HOME",
    _HOME / ".cache",
)
_DATA_HOME = _xdg_base_directory(
    "XDG_DATA_HOME",
    _HOME / ".local" / "share",
)

# Diagnostics are initialized before GTK is imported so fatal native faults
# during GTK/libadwaita startup still have a persistent destination.
_EARLY_STATE_PATH = _STATE_HOME / "verselatch"
_FAULT_LOG_PATH = _EARLY_STATE_PATH / "fault.log"
_FAULT_LOG_FD: int | None = None

try:
    _ensure_private_directory(_EARLY_STATE_PATH)

    if (
        _FAULT_LOG_PATH.is_file()
        and not _FAULT_LOG_PATH.is_symlink()
        and _FAULT_LOG_PATH.stat().st_size > 512 * 1024
    ):
        previous_fault = _FAULT_LOG_PATH.with_suffix(
            ".log.1"
        )
        try:
            previous_fault.unlink()
        except FileNotFoundError:
            pass
        os.replace(
            _FAULT_LOG_PATH,
            previous_fault,
        )

    fault_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        fault_flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        fault_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        fault_flags |= os.O_NONBLOCK

    _FAULT_LOG_FD = os.open(
        _FAULT_LOG_PATH,
        fault_flags,
        0o600,
    )
    fault_metadata = os.fstat(_FAULT_LOG_FD)
    if not stat.S_ISREG(fault_metadata.st_mode):
        os.close(_FAULT_LOG_FD)
        _FAULT_LOG_FD = None
        raise OSError(
            "Fault log path is not a regular file."
        )
    os.fchmod(_FAULT_LOG_FD, 0o600)
    try:
        faulthandler.enable(
            _FAULT_LOG_FD,
            all_threads=True,
            c_stack=True,
        )
    except TypeError:
        # c_stack was added in Python 3.14. Keep the package compatible
        # with the declared Python 3.10+ floor.
        faulthandler.enable(
            _FAULT_LOG_FD,
            all_threads=True,
        )
except Exception:
    _FAULT_LOG_FD = None
    try:
        faulthandler.enable(
            all_threads=True,
        )
    except Exception:
        pass


# Deliberately delayed until crash diagnostics are initialized. PyGObject
# requires require_version() before importing the corresponding repository
# namespaces; the E402 suppression is therefore narrow and intentional.
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    from gi.repository import GLibUnix  # noqa: E402
except (ImportError, ValueError):
    GLibUnix = None


APP_NAME = "VerseLatch"
APP_VERSION = "1.0.1"
APP_ID = "io.github.erhansavas.verselatch"
MIN_GTK_VERSION = (4, 16)
MIN_ADW_VERSION = (1, 8)

STATE_PATH = _EARLY_STATE_PATH
APP_LOG_PATH = STATE_PATH / "app.log"
STDERR_LOG_PATH = STATE_PATH / "stderr.log"
FAULT_LOG_PATH = _FAULT_LOG_PATH
LAST_EXIT_PATH = STATE_PATH / "last-exit.txt"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("verselatch")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    try:
        _ensure_private_directory(STATE_PATH)

        handler = NoFollowRotatingFileHandler(
            APP_LOG_PATH,
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
            "%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger


LOGGER = configure_logging()


def _uncaught_exception_hook(exc_type, exc_value, exc_traceback) -> None:
    try:
        LOGGER.critical(
            "uncaught main-thread exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
    finally:
        sys.__excepthook__(
            exc_type,
            exc_value,
            exc_traceback,
        )


def _thread_exception_hook(args) -> None:
    try:
        LOGGER.critical(
            "uncaught worker-thread exception in %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            ),
        )
    finally:
        threading.__excepthook__(args)


sys.excepthook = _uncaught_exception_hook
threading.excepthook = _thread_exception_hook


def tail_text_file(
    path: Path,
    *,
    maximum_lines: int = 80,
    maximum_bytes: int = 64 * 1024,
) -> str:
    descriptor = -1
    try:
        descriptor, metadata = open_regular_readonly(
            path,
            description="Diagnostics file",
        )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            handle.seek(max(0, metadata.st_size - maximum_bytes))
            text = handle.read(maximum_bytes).decode(
                "utf-8",
                errors="replace",
            )
        return "\n".join(text.splitlines()[-maximum_lines:])
    except (OSError, VerseLatchError):
        return ""
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def print_diagnostics() -> None:
    print(f"{APP_NAME} {APP_VERSION} diagnostics")
    print(f"State directory: {STATE_PATH}")
    print(f"Application log: {APP_LOG_PATH}")
    print(f"GTK/stderr log:  {STDERR_LOG_PATH}")
    print(f"Fatal fault log: {FAULT_LOG_PATH}")
    print(f"Last exit:       {LAST_EXIT_PATH}")

    for title, path in (
        ("LAST EXIT", LAST_EXIT_PATH),
        ("APPLICATION LOG", APP_LOG_PATH),
        ("STDERR / GTK LOG", STDERR_LOG_PATH),
        ("FATAL FAULT LOG", FAULT_LOG_PATH),
    ):
        content = tail_text_file(path)
        if content:
            print(f"\n--- {title} ---")
            print(content)

DEFAULT_THEME = "system"
THEME_OPTIONS = (
    ("Follow System", "system"),
    ("Light", "light"),
    ("Dark", "dark"),
)
THEME_IDS = frozenset(value for _label, value in THEME_OPTIONS)

ASR_MODEL_PATH = (
    _DATA_HOME
    / "verselatch"
    / "models"
    / "ggml-large-v3-turbo.bin"
)

ASR_MODEL_SIZE = 1624555275
ASR_MODEL_SHA256 = (
    "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"
)
_VERIFIED_ASR_MODEL_STATE: tuple[int, int, int, int, int] | None = None
_ASR_MODEL_VERIFICATION_LOCK = threading.Lock()

THEME_PATH = (
    _CONFIG_HOME
    / "verselatch"
    / "theme"
)

ASR_CACHE_PATH = (
    _CACHE_HOME
    / "verselatch"
    / "asr"
)

ASR_CACHE_SCHEMA = 7
MAX_ASR_CACHE_ENTRIES = 12
MAX_ASR_CACHE_BYTES = 32 * 1024 * 1024

_LOGICAL_CPUS = max(1, os.cpu_count() or 4)
ASR_THREADS = max(
    1,
    min(
        8,
        _LOGICAL_CPUS if _LOGICAL_CPUS <= 4 else _LOGICAL_CPUS // 2,
    ),
)
ASR_MAX_SEGMENT_CHARS = 56
SYSTEM_EXEC_PATH = "/usr/bin:/bin"
WHISPER_CLI = shutil.which("whisper-cli", path=SYSTEM_EXEC_PATH)
AUBIOTRACK = shutil.which("aubiotrack", path=SYSTEM_EXEC_PATH)
AUBIOONSET = shutil.which("aubioonset", path=SYSTEM_EXEC_PATH)
PRLIMIT = shutil.which("prlimit", path=SYSTEM_EXEC_PATH)
MAX_RHYTHM_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_WHISPER_OUTPUT_BYTES = 32 * 1024 * 1024

SUPPORTED_AUDIO = {
    ".flac",
    ".mp3",
    ".ogg",
    ".wav",
}

SUPPORTED_LYRICS = {
    ".lrc",
    ".txt",
}

WHISPER_LANGUAGE_CODES = frozenset(
    {
        "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo",
        "br", "bs", "ca", "cs", "cy", "da", "de", "el", "en", "es",
        "et", "eu", "fa", "fi", "fo", "fr", "gl", "gu", "ha", "haw",
        "he", "hi", "hr", "ht", "hu", "hy", "id", "is", "it", "ja",
        "jw", "ka", "kk", "km", "kn", "ko", "la", "lb", "ln", "lo",
        "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
        "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt",
        "ro", "ru", "sa", "sd", "si", "sk", "sl", "sn", "so", "sq",
        "sr", "su", "sv", "sw", "ta", "te", "tg", "th", "tk", "tl",
        "tr", "tt", "uk", "ur", "uz", "vi", "yi", "yo", "yue", "zh",
    }
)


def normalize_language_hint(value: str) -> str:
    """Return a whisper.cpp language code or `auto` for an empty hint."""
    normalized = value.strip().casefold()
    if not normalized or normalized == "auto":
        return "auto"
    if normalized not in WHISPER_LANGUAGE_CODES:
        raise VerseLatchError(
            "Unsupported language code. Use a Whisper language code such as "
            "tr, en, de, fr, or es, or leave it blank for automatic detection."
        )
    return normalized


def is_supported_lyrics_path(path: Path) -> bool:
    name = path.name.casefold()
    return (
        path.suffix.casefold() in SUPPORTED_LYRICS
        or ".lrc.bak-" in name
    )

MAX_AUDIO_BYTES = 512 * 1024 * 1024


MIN_AVAILABLE_MEMORY_MIB = 3200


def resolve_audio_selection(path: str | Path) -> Path:
    candidate = Path(path).expanduser()

    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise VerseLatchError(
            "Audio source does not exist or cannot be inspected safely."
        ) from exc

    if stat.S_ISLNK(metadata.st_mode):
        raise VerseLatchError(
            "Audio file must not be a symbolic link."
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise VerseLatchError(
            "Audio source must be a regular file."
        )
    if candidate.suffix.casefold() not in SUPPORTED_AUDIO:
        raise VerseLatchError(
            "Supported formats: FLAC, MP3, OGG, WAV."
        )
    if metadata.st_size > MAX_AUDIO_BYTES:
        raise VerseLatchError(
            "Audio exceeds the 512 MiB safety limit."
        )

    initial_state = file_state_tuple(metadata)

    try:
        resolved = candidate.resolve(strict=True)
        resolved_state = regular_file_state(
            resolved,
            description="Audio source",
            maximum_bytes=MAX_AUDIO_BYTES,
        )
    except OSError as exc:
        raise VerseLatchError(
            "Audio source could not be resolved safely."
        ) from exc

    if resolved_state != initial_state:
        raise VerseLatchError(
            "Audio source changed while it was being selected. Try again."
        )

    return resolved


def resolve_lyrics_selection(path: str | Path) -> Path:
    candidate = Path(path).expanduser()

    try:
        metadata = os.lstat(candidate)
    except OSError as exc:
        raise VerseLatchError(
            "Lyrics source does not exist or cannot be inspected safely."
        ) from exc

    if stat.S_ISLNK(metadata.st_mode):
        raise VerseLatchError(
            "Lyrics file must not be a symbolic link."
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise VerseLatchError(
            "Lyrics source must be a regular file."
        )
    if not is_supported_lyrics_path(candidate):
        raise VerseLatchError(
            "Choose an .lrc, VerseLatch .lrc backup, or .txt file."
        )

    initial_state = file_state_tuple(metadata)

    try:
        resolved = candidate.resolve(strict=True)
        resolved_state = regular_file_state(
            resolved,
            description="Lyrics source",
            maximum_bytes=MAX_LYRICS_BYTES,
        )
    except OSError as exc:
        raise VerseLatchError(
            "Lyrics source could not be resolved safely."
        ) from exc

    if resolved_state != initial_state:
        raise VerseLatchError(
            "Lyrics source changed while it was being selected. Try again."
        )

    return resolved


def available_memory_mib() -> int:
    try:
        with open(
            "/proc/meminfo",
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    kib = int(line.split()[1])
                    return max(0, kib // 1024)
    except (OSError, ValueError, IndexError):
        pass

    try:
        pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if pages >= 0 and page_size > 0:
            return (pages * page_size) // (1024 * 1024)
    except (OSError, ValueError, TypeError):
        pass

    # Resource safety is fail-closed: unknown is not treated as unlimited RAM.
    return 0


def _verify_regular_file_sha256(
    path: Path,
    *,
    description: str,
    expected_size: int,
    expected_sha256: str,
    cancel_event: threading.Event | None = None,
) -> os.stat_result:
    """Hash one stable regular file without following its leaf symlink."""
    descriptor, metadata = open_regular_readonly(
        path,
        description=description,
    )
    if metadata.st_size != expected_size:
        os.close(descriptor)
        raise VerseLatchError(
            f"{description} has an unexpected size; reinstall it."
        )

    before_state = file_state_tuple(metadata)
    digest = hashlib.sha256()

    try:
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise AnalysisCancelled()

                chunk = handle.read(4 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)

            after = os.fstat(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if file_state_tuple(after) != before_state:
        raise VerseLatchError(
            f"{description} changed while it was being verified; try again."
        )
    if digest.hexdigest() != expected_sha256:
        raise VerseLatchError(
            f"{description} failed its SHA-256 integrity check; reinstall it."
        )
    return after


def validate_model_file(
    *,
    verify_digest: bool = False,
    cancel_event: threading.Event | None = None,
) -> os.stat_result:
    """Validate the pinned model, hashing it once per application process."""
    global _VERIFIED_ASR_MODEL_STATE

    descriptor, metadata = open_regular_readonly(
        ASR_MODEL_PATH,
        description="Required Whisper model",
    )
    os.close(descriptor)
    if metadata.st_size != ASR_MODEL_SIZE:
        raise VerseLatchError(
            "Required Whisper model has an unexpected size; reinstall it."
        )

    state = file_state_tuple(metadata)
    if not verify_digest:
        if (
            _VERIFIED_ASR_MODEL_STATE is not None
            and _VERIFIED_ASR_MODEL_STATE != state
        ):
            raise VerseLatchError(
                "Required Whisper model changed after verification; "
                "reinstall it."
            )
        return metadata
    if _VERIFIED_ASR_MODEL_STATE == state:
        return metadata

    with _ASR_MODEL_VERIFICATION_LOCK:
        if _VERIFIED_ASR_MODEL_STATE == state:
            return metadata

        verified = _verify_regular_file_sha256(
            ASR_MODEL_PATH,
            description="Required Whisper model",
            expected_size=ASR_MODEL_SIZE,
            expected_sha256=ASR_MODEL_SHA256,
            cancel_event=cancel_event,
        )
        _VERIFIED_ASR_MODEL_STATE = file_state_tuple(verified)
        return verified


def build_asr_cache_key(
    audio: Path,
    *,
    language: str,
    cancel_event: threading.Event | None = None,
) -> tuple[str, tuple[int, int, int, int, int]]:
    """Return a content-bound ASR cache key and represented audio state."""
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled()

    if WHISPER_CLI is None:
        raise VerseLatchError(
            "whisper-cli is not installed."
        )

    model = validate_model_file()

    descriptor, before = open_regular_readonly(
        audio,
        description="Audio source",
        maximum_bytes=MAX_AUDIO_BYTES,
    )
    digest = hashlib.sha256()

    try:
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            while True:
                if (
                    cancel_event is not None
                    and cancel_event.is_set()
                ):
                    raise AnalysisCancelled()

                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)

            after = os.fstat(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    before_state = file_state_tuple(before)
    after_state = file_state_tuple(after)

    if before_state != after_state:
        raise VerseLatchError(
            "Audio changed while it was being read. Try again."
        )

    cli_path = Path(WHISPER_CLI)
    cli = cli_path.stat()

    identity = {
        "schema": ASR_CACHE_SCHEMA,
        "audio_sha256": digest.hexdigest(),
        "audio_size": before.st_size,
        "model_path": str(ASR_MODEL_PATH.resolve()),
        "model_sha256": ASR_MODEL_SHA256,
        "model_size": model.st_size,
        "model_mtime_ns": model.st_mtime_ns,
        "whisper_path": str(cli_path.resolve()),
        "whisper_size": cli.st_size,
        "whisper_mtime_ns": cli.st_mtime_ns,
        "threads": ASR_THREADS,
        "acceleration": "automatic",
        "language": language,
        "segment_max_chars": ASR_MAX_SEGMENT_CHARS,
        "split_on_word": True,
        "decode_profile": "quality-v3",
        "suppress_non_speech_tokens": True,
    }

    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return (
        hashlib.sha256(encoded).hexdigest(),
        before_state,
    )


def load_asr_cache(
    cache_key: str,
) -> list[dict] | None:
    if (
        re.fullmatch(r"[0-9a-f]{64}", cache_key) is None
        or not _is_safe_private_directory(ASR_CACHE_PATH)
    ):
        return None

    cache_file = ASR_CACHE_PATH / f"{cache_key}.json"
    descriptor = -1

    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK

        descriptor = os.open(cache_file, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > MAX_ASR_CACHE_BYTES
        ):
            return None

        with os.fdopen(
            descriptor,
            "r",
            encoding="utf-8",
            errors="strict",
        ) as handle:
            descriptor = -1
            payload = json.load(handle)

        if (
            not isinstance(payload, dict)
            or payload.get("schema") != ASR_CACHE_SCHEMA
        ):
            return None

        segments = validate_asr_segments(
            payload.get("segments")
        )

        if segments is None:
            return None

        os.utime(
            cache_file,
            follow_symlinks=False,
        )

        return segments

    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def store_asr_cache(
    cache_key: str,
    segments: list[dict],
) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", cache_key) is None:
        return

    validated = validate_asr_segments(
        segments
    )

    if validated is None:
        return

    temporary: str | None = None

    try:
        _ensure_private_directory(ASR_CACHE_PATH)

        fd, temporary = tempfile.mkstemp(
            prefix=".asr-",
            suffix=".tmp",
            dir=str(ASR_CACHE_PATH),
        )

        os.fchmod(fd, 0o600)
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(
                {
                    "schema": ASR_CACHE_SCHEMA,
                    "segments": validated,
                },
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        destination = (
            ASR_CACHE_PATH
            / f"{cache_key}.json"
        )

        # Re-check the leaf directory before replacement/pruning so an
        # accidental symlink swap cannot redirect app-owned cleanup.
        if not _is_safe_private_directory(ASR_CACHE_PATH):
            raise OSError(
                "ASR cache directory became unsafe."
            )

        os.replace(
            temporary,
            destination,
        )
        temporary = None

        entries = []
        for path in ASR_CACHE_PATH.glob("*.json"):
            try:
                metadata = path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode):
                entries.append((metadata.st_mtime_ns, path))

        entries.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        for _, old in entries[MAX_ASR_CACHE_ENTRIES:]:
            old.unlink()

    except OSError:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def recover_matching_backup_timing(
    lyrics_path: Path,
    entries: list[dict],
) -> tuple[list[dict], Path | None]:
    """Recover timing from a VerseLatch-created backup when safe to do so.

    Recovery is intentionally narrow: only same-directory, regular,
    non-symlink ``<selected-name>.bak-*`` files with exactly matching lyric
    text and sane monotonic timing qualify. Words always come from the selected
    file; only the prior timestamps are recovered.
    """
    if not timing_pattern_is_suspicious(entries):
        return entries, None

    candidates: list[tuple[int, Path, list[dict]]] = []

    for candidate in lyrics_path.parent.glob(
        lyrics_path.name + ".bak-*"
    ):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue

            metadata = candidate.stat()
            if metadata.st_size > MAX_LYRICS_BYTES:
                continue

            document = parse_lyric_document(
                safe_read_text(candidate)
            )
            backup_entries = document["entries"]

            if not same_lyric_text(entries, backup_entries):
                continue

            if any(
                item.get("source_time") is None
                for item in backup_entries
            ):
                continue

            if timing_pattern_is_suspicious(backup_entries):
                continue

            candidates.append(
                (
                    metadata.st_mtime_ns,
                    candidate,
                    backup_entries,
                )
            )
        except (OSError, VerseLatchError):
            continue

    if not candidates:
        return entries, None

    _, backup_path, backup_entries = max(
        candidates,
        key=lambda item: item[0],
    )

    recovered = [
        {
            "text": selected["text"],
            "source_time": backup["source_time"],
        }
        for selected, backup in zip(entries, backup_entries)
    ]

    return recovered, backup_path


def load_theme() -> str:
    descriptor = -1
    try:
        if not _is_safe_private_directory(THEME_PATH.parent):
            return DEFAULT_THEME

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK

        descriptor = os.open(THEME_PATH, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > 64
        ):
            return DEFAULT_THEME

        with os.fdopen(
            descriptor,
            "r",
            encoding="utf-8",
            errors="strict",
        ) as handle:
            descriptor = -1
            value = handle.read().strip().lower()

        if value in THEME_IDS:
            return value

    except (OSError, UnicodeError):
        pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    return DEFAULT_THEME


def store_theme(
    theme: str,
) -> None:
    if theme not in THEME_IDS:
        return

    temporary: str | None = None

    try:
        _ensure_private_directory(THEME_PATH.parent)

        fd, temporary = tempfile.mkstemp(
            prefix=".theme-",
            suffix=".tmp",
            dir=str(THEME_PATH.parent),
        )
        os.fchmod(fd, 0o600)

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(theme + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        if not _is_safe_private_directory(THEME_PATH.parent):
            raise OSError(
                "Theme directory became unsafe."
            )

        os.replace(
            temporary,
            THEME_PATH,
        )
        temporary = None

    except OSError:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def css_for() -> str:
    # Keep custom CSS structural only. Libadwaita owns typography, colors,
    # semantic action states, focus rendering, dark/light appearance, and
    # high-contrast behavior.
    return """
    window.verselatch-window .panel-content { padding: 16px; }
    window.verselatch-window .verification-icon { -gtk-icon-size: 18px; }
    window.verselatch-window textview.result-text { padding: 14px; }
    """

def tail_binary_file(
    handle,
    *,
    maximum_bytes: int = 16 * 1024,
) -> str:
    try:
        handle.flush()
        handle.seek(
            0,
            os.SEEK_END,
        )
        size = handle.tell()
        handle.seek(
            max(
                0,
                size - maximum_bytes,
            )
        )
        return handle.read().decode(
            "utf-8",
            errors="replace",
        ).strip()
    except (OSError, ValueError):
        return ""


class MainWindow(
    Adw.ApplicationWindow
):
    def __init__(
        self,
        application,
    ):
        super().__init__(
            application=application
        )

        self.set_title(
            APP_NAME
        )

        self.add_css_class(
            "verselatch-window"
        )

        # The startup view is deliberately compact. Results expand into the
        # existing scroller instead of forcing an empty 900x720 canvas.
        self.set_default_size(
            800,
            600,
        )

        # Keep a small hard minimum for large text and compact desktops; all
        # workbench content remains vertically scrollable.
        self.set_size_request(
            420,
            420,
        )

        self.audio_path: (
            Path | None
        ) = None

        self.lyrics_path: (
            Path | None
        ) = None

        self.output_text = ""

        self.output_allowed = False
        self.analyzed_audio_path: Path | None = None
        self.analyzed_audio_state: tuple[int, int, int, int, int] | None = None
        self.analyzed_lyrics_path: Path | None = None
        self.analyzed_lyrics_state: tuple[int, int, int, int, int] | None = None
        self.setting_preview = False

        # Save completion belongs to the current explicit source selection.
        # A successful save stays completed until the user changes audio or
        # lyrics input. Re-analysis alone does not reset that completion state.
        self.input_generation = 0
        self.save_completed_generation: int | None = None
        self.save_state = "unavailable"
        self.analysis_retry_recommended = False

        self.current_process = None
        self.process_lock = (
            threading.Lock()
        )

        self.analysis_active = False
        self.analysis_cancel = threading.Event()
        self.analysis_thread: threading.Thread | None = None
        # Monotonic run identifier prevents a delayed GLib callback from an
        # older worker from mutating UI state belonging to a newer analysis.
        self.analysis_run_id = 0

        self.closing = False
        self.close_pending = False
        self.force_close = False

        self.css_provider = (
            Gtk.CssProvider()
        )

        self.css_errors: list[str] = []

        self.css_provider.connect(
            "parsing-error",
            self.on_css_parsing_error,
        )

        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.connect(
            "notify::high-contrast",
            self.on_high_contrast_changed,
        )

        self.current_theme = load_theme()
        self.theme_action = Gio.SimpleAction.new_stateful(
            "theme",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(self.current_theme),
        )
        self.theme_action.connect(
            "change-state",
            self.on_theme_action_changed,
        )
        self.add_action(self.theme_action)

        display = (
            Gdk.Display
            .get_default()
        )

        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        self.build_ui()

        self.apply_theme(
            self.current_theme
        )

        self.connect(
            "close-request",
            self.on_close_request,
        )

        close_action = Gio.SimpleAction.new(
            "close",
            None,
        )

        close_action.connect(
            "activate",
            self.close_window,
        )

        self.add_action(
            close_action
        )

        application.set_accels_for_action(
            "win.close",
            ["<Control>w"],
        )

        about_action = Gio.SimpleAction.new(
            "about",
            None,
        )
        about_action.connect(
            "activate",
            self.show_about,
        )
        self.add_action(
            about_action
        )

        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self.show_shortcuts)
        self.add_action(shortcuts_action)

        open_audio_action = Gio.SimpleAction.new("open-audio", None)
        open_audio_action.connect("activate", self.open_audio_shortcut)
        self.add_action(open_audio_action)

        open_lyrics_action = Gio.SimpleAction.new("open-lyrics", None)
        open_lyrics_action.connect("activate", self.open_lyrics_shortcut)
        self.add_action(open_lyrics_action)

        save_action = Gio.SimpleAction.new("save", None)
        save_action.connect("activate", self.save_shortcut)
        self.add_action(save_action)

        application.set_accels_for_action("win.open-audio", ["<Control>o"])
        application.set_accels_for_action("win.open-lyrics", ["<Control><Shift>o"])
        application.set_accels_for_action("win.save", ["<Control>s"])
        application.set_accels_for_action("win.shortcuts", ["<Control>question"])

    def on_css_parsing_error(
        self,
        _provider,
        section,
        error,
    ) -> None:
        self.css_errors.append(
            f"{section}: {error.message}"
        )

    def close_window(
        self,
        _action,
        _parameter,
    ) -> None:
        self.close()

    def open_audio_shortcut(
        self,
        _action,
        _parameter,
    ) -> None:
        if not self.is_busy():
            self.choose_audio(None)

    def open_lyrics_shortcut(
        self,
        _action,
        _parameter,
    ) -> None:
        if not self.is_busy():
            self.choose_lyrics(None)

    def save_shortcut(
        self,
        _action,
        _parameter,
    ) -> None:
        if hasattr(self, "save_button") and self.save_button.get_sensitive():
            self.save_result(None)

    def show_shortcuts(
        self,
        _action,
        _parameter,
    ) -> None:
        dialog = Adw.ShortcutsDialog()

        files = Adw.ShortcutsSection.new("Files")
        files.add(Adw.ShortcutsItem.new_from_action("Open Audio", "win.open-audio"))
        files.add(Adw.ShortcutsItem.new_from_action("Open Lyrics", "win.open-lyrics"))
        files.add(Adw.ShortcutsItem.new_from_action("Save LRC", "win.save"))
        dialog.add(files)

        general = Adw.ShortcutsSection.new("General")
        general.add(Adw.ShortcutsItem.new("Main Menu", "F10"))
        general.add(Adw.ShortcutsItem.new_from_action("Keyboard Shortcuts", "win.shortcuts"))
        general.add(Adw.ShortcutsItem.new_from_action("Close Window", "win.close"))
        dialog.add(general)
        dialog.present(self)

    def show_about(
        self,
        _action,
        _parameter,
    ) -> None:
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name="erhansavas",
            copyright="© 2026 erhansavas",
            website="https://github.com/erhansavas/verselatch",
            issue_url="https://github.com/erhansavas/verselatch/issues",
            comments=(
                "Create, verify, and align LRC timing.\n\n"
                "Processing is local. VerseLatch does not send telemetry "
                "or run a background service."
            ),
            license_type=Gtk.License.GPL_3_0_ONLY,
        )
        dialog.add_legal_section(
            "AppStream metadata — MIT",
            "© 2026 erhansavas",
            Gtk.License.CUSTOM,
            "The AppStream metadata is licensed under the MIT License.",
        )
        dialog.present(self)

    def build_ui(
        self,
    ):
        toolbar = Adw.ToolbarView()
        toolbar.set_top_bar_style(Adw.ToolbarStyle.FLAT)

        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title=APP_NAME)
        header.set_title_widget(title)

        menu = Gio.Menu()
        appearance_section = Gio.Menu()
        appearance_menu = Gio.Menu()
        for label, target in THEME_OPTIONS:
            item = Gio.MenuItem.new(label, "win.theme")
            item.set_attribute_value(
                "target",
                GLib.Variant.new_string(target),
            )
            appearance_menu.append_item(item)
        appearance_section.append_submenu("Appearance", appearance_menu)
        menu.append_section(None, appearance_section)

        about_section = Gio.Menu()
        about_section.append("Keyboard Shortcuts", "win.shortcuts")
        about_section.append("About VerseLatch", "win.about")
        menu.append_section(None, about_section)

        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
        )
        menu_button.set_primary(True)
        menu_button.set_tooltip_text("Main Menu")
        menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Main Menu"],
        )
        header.pack_end(menu_button)
        toolbar.add_top_bar(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_valign(Gtk.Align.START)
        clamp.set_maximum_size(680)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_valign(Gtk.Align.START)
        content.set_margin_top(28)
        content.set_margin_bottom(28)
        content.set_margin_start(16)
        content.set_margin_end(16)
        clamp.set_child(content)
        scroll.set_child(clamp)

        # A single task-oriented heading and one unified input surface keep the
        # first view calm and contemporary. The workbench avoids dashboard
        # decoration and preferences-style section stacking.
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        intro_title = Gtk.Label(label="Create LRC")
        intro_title.set_xalign(0)
        intro_title.add_css_class("title-2")
        intro.append(intro_title)

        intro_copy = Gtk.Label(
            label=(
                "Choose audio, then add lyrics to align or leave them empty "
                "to create a draft"
            )
        )
        intro_copy.set_xalign(0)
        intro_copy.set_wrap(True)
        intro_copy.add_css_class("body")
        intro_copy.add_css_class("dimmed")
        intro.append(intro_copy)
        content.append(intro)

        input_group = Adw.PreferencesGroup()

        self.audio_row = Adw.ActionRow(
            title="Audio",
            subtitle="No file selected",
        )
        self.audio_row.set_subtitle_lines(1)
        self.audio_button = Gtk.Button(label="Choose…")
        self.audio_button.set_valign(Gtk.Align.CENTER)
        self.audio_button.set_tooltip_text("Choose an audio file")
        self.audio_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Choose an audio file"],
        )
        self.audio_button.connect("clicked", self.choose_audio)
        self.audio_row.add_suffix(self.audio_button)
        self.audio_row.set_activatable_widget(self.audio_button)
        input_group.add(self.audio_row)

        self.lyrics_row = Adw.ActionRow(
            title="Lyrics",
            subtitle="No file selected",
        )
        self.lyrics_row.set_subtitle_lines(1)
        lyrics_actions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        lyrics_actions.set_valign(Gtk.Align.CENTER)

        self.clear_button = Gtk.Button(icon_name="edit-clear-symbolic")
        self.clear_button.add_css_class("flat")
        self.clear_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Clear the lyrics selection"],
        )
        self.clear_button.set_sensitive(False)
        self.clear_button.set_visible(False)
        self.clear_button.set_tooltip_text("Clear the selected lyrics file")
        self.clear_button.connect("clicked", self.clear_lyrics)

        self.lyrics_button = Gtk.Button(label="Choose…")
        self.lyrics_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Choose a lyrics file"],
        )
        self.lyrics_button.set_tooltip_text("Choose an LRC or TXT file")
        self.lyrics_button.connect("clicked", self.choose_lyrics)
        lyrics_actions.append(self.clear_button)
        lyrics_actions.append(self.lyrics_button)
        self.lyrics_row.add_suffix(lyrics_actions)
        self.lyrics_row.set_activatable_widget(self.lyrics_button)
        input_group.add(self.lyrics_row)

        self.language_entry = Adw.EntryRow(title="Language")
        self.language_entry.set_max_length(8)
        self.language_entry.set_tooltip_text(
            "Optional Whisper language code. Leave blank for automatic detection"
        )
        self.language_entry.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Language code, optional. Examples: tr, en, ru"],
        )
        self.language_example = Gtk.Label(label="tr, en, ru")
        self.language_example.set_valign(Gtk.Align.CENTER)
        self.language_example.add_css_class("caption")
        self.language_example.add_css_class("dimmed")
        self.language_example.set_tooltip_text(
            "Example language codes; leave blank for automatic detection"
        )
        self.language_entry.add_suffix(self.language_example)
        self.language_entry.connect("changed", self.on_language_changed)
        input_group.add(self.language_entry)
        content.append(input_group)

        # Status is lightweight contextual feedback, not another boxed list.
        # The primary action sits in open space as a pill, matching current
        # GNOME guidance for a single primary action outside a header bar.
        action_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        action_bar.set_margin_top(2)

        status_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        status_box.set_hexpand(True)
        status_box.set_valign(Gtk.Align.CENTER)

        self.spinner = Gtk.Spinner()
        self.spinner.set_valign(Gtk.Align.CENTER)
        status_box.append(self.spinner)

        self.status_label = Gtk.Label(label="Choose an audio file to begin")
        self.status_label.set_xalign(0)
        self.status_label.set_hexpand(True)
        self.status_label.set_wrap(True)
        self.status_label.add_css_class("caption")
        self.status_label.add_css_class("dimmed")
        status_box.append(self.status_label)

        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.add_css_class("flat")
        self.cancel_button.set_visible(False)
        self.cancel_button.set_sensitive(False)
        self.cancel_button.set_tooltip_text("Cancel the current analysis")
        self.cancel_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Cancel analysis"],
        )
        self.cancel_button.connect("clicked", self.cancel_analysis)
        status_box.append(self.cancel_button)
        action_bar.append(status_box)

        self.analyze_button = Gtk.Button(label="Generate Draft")
        self.analyze_button.add_css_class("pill")
        self.analyze_button.set_valign(Gtk.Align.CENTER)
        self.analyze_button.set_sensitive(False)
        self.analyze_button.set_tooltip_text("Analyze the selected audio file")
        self.analyze_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Generate an editable lyrics draft"],
        )
        self.analyze_button.connect("clicked", self.start_analysis)
        action_bar.append(self.analyze_button)
        content.append(action_bar)

        # Results remain progressive disclosure: they do not consume space
        # until analysis produces something meaningful.
        self.results_group = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=16,
        )
        self.results_group.set_visible(False)

        verification_card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
        )
        verification_card.add_css_class("card")
        verification_card.add_css_class("panel-content")

        verification_title = Gtk.Label(label="Verification")
        verification_title.set_xalign(0)
        verification_title.add_css_class("heading")
        verification_card.append(verification_title)

        verdict_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.verification_icon = Gtk.Image.new_from_icon_name(
            "dialog-information-symbolic"
        )
        self.verification_icon.add_css_class("verification-icon")
        verdict_row.append(self.verification_icon)

        self.verification_state = Gtk.Label(label="No analysis yet")
        self.verification_state.set_xalign(0)
        self.verification_state.set_hexpand(True)
        self.verification_state.set_wrap(True)
        verdict_row.append(self.verification_state)
        verification_card.append(verdict_row)

        self.verification_note = Gtk.Label(
            label="Verification details will appear after analysis"
        )
        self.verification_note.set_xalign(0)
        self.verification_note.set_wrap(True)
        self.verification_note.add_css_class("dimmed")
        verification_card.append(self.verification_note)

        self.metrics_row = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
        )
        self.metrics_row.set_visible(False)

        def make_metric(label: str):
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=12,
            )
            name = Gtk.Label(label=label)
            name.set_xalign(0)
            name.set_hexpand(True)
            name.add_css_class("dimmed")
            value = Gtk.Label(label="—")
            value.set_xalign(1)
            value.add_css_class("numeric")
            value.add_css_class("heading")
            row.append(name)
            row.append(value)
            self.metrics_row.append(row)
            return value

        self.confidence_value = make_metric("Confidence")
        self.anchors_value = make_metric("Strong Matches")
        self.review_value = make_metric("Needs Review")
        verification_card.append(self.metrics_row)

        self.report_frame = Gtk.ScrolledWindow()
        self.report_frame.set_min_content_height(130)
        self.report_frame.set_max_content_height(190)
        self.report_frame.set_propagate_natural_height(True)
        self.report_frame.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.report_frame.add_css_class("frame")
        self.report_frame.add_css_class("view")
        self.report_frame.set_visible(False)

        self.report_view = Gtk.TextView()
        self.report_view.set_editable(False)
        self.report_view.set_cursor_visible(False)
        self.report_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.report_view.add_css_class("result-text")
        self.report_view.add_css_class("monospace")
        self.report_frame.set_child(self.report_view)

        self.technical_expander = Gtk.Expander(label="Technical Details")
        self.technical_expander.set_expanded(False)
        self.technical_expander.set_visible(False)
        self.technical_expander.set_child(self.report_frame)
        verification_card.append(self.technical_expander)
        self.results_group.append(verification_card)

        self.preview_card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
        )
        self.preview_card.add_css_class("card")
        self.preview_card.add_css_class("panel-content")

        preview_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        preview_title = Gtk.Label(label="LRC Preview")
        preview_title.set_xalign(0)
        preview_title.set_hexpand(True)
        preview_title.add_css_class("heading")

        self.save_button = Gtk.Button(label="Save LRC")
        self.save_button.set_sensitive(False)
        self.save_button.set_tooltip_text("Save the reviewed sidecar LRC")
        self.save_button.connect("clicked", self.save_result)
        preview_header.append(preview_title)
        preview_header.append(self.save_button)
        self.preview_card.append(preview_header)

        self.save_feedback = Gtk.Label(label="")
        self.save_feedback.set_xalign(0)
        self.save_feedback.set_wrap(True)
        self.save_feedback.set_visible(False)
        self.save_feedback.add_css_class("caption")
        self.preview_card.append(self.save_feedback)

        self.preview_view = Gtk.TextView()
        self.preview_view.set_editable(True)
        self.preview_view.set_cursor_visible(True)
        self.preview_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.preview_view.add_css_class("result-text")
        self.preview_view.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Editable LRC preview"],
        )

        preview_buffer = self.preview_view.get_buffer()
        self.timestamp_tag = preview_buffer.create_tag(
            "timestamp",
            family="monospace",
        )
        preview_buffer.connect("changed", self.on_preview_changed)

        self.review_check = Gtk.CheckButton(
            label="Lyrics and timestamps reviewed"
        )
        self.review_check.set_visible(False)
        self.review_check.set_tooltip_text(
            "Confirm that the complete LRC was reviewed before saving"
        )
        self.review_check.update_property(
            [Gtk.AccessibleProperty.LABEL],
            ["Confirm that lyrics and timestamps were reviewed"],
        )
        self.review_check.connect("toggled", self.on_review_toggled)

        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_min_content_height(290)
        preview_scroll.set_policy(
            Gtk.PolicyType.NEVER,
            Gtk.PolicyType.AUTOMATIC,
        )
        preview_scroll.add_css_class("frame")
        preview_scroll.add_css_class("view")
        preview_scroll.set_child(self.preview_view)
        self.preview_card.append(preview_scroll)
        self.preview_card.append(self.review_check)
        self.results_group.append(self.preview_card)
        content.append(self.results_group)

        footer = Gtk.Label(label="GPL-3.0-only · © 2026 erhansavas")
        footer.set_halign(Gtk.Align.CENTER)
        footer.set_wrap(True)
        footer.set_margin_top(4)
        footer.set_margin_bottom(12)
        footer.set_margin_start(12)
        footer.set_margin_end(12)
        footer.add_css_class("caption")
        footer.add_css_class("dimmed")
        footer.set_tooltip_text(
            "License details are available in About VerseLatch"
        )

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(scroll)
        page.append(footer)
        toolbar.set_content(page)
        self.set_content(toolbar)

    def set_status(
        self,
        text: str,
    ) -> None:
        self.status_label.set_text(text)

    def refresh_primary_action_style(
        self,
    ) -> None:
        # Semantic accent belongs only to the single action that is both valid
        # and currently expected. Disabled actions stay visually neutral.
        self.analyze_button.remove_css_class("suggested-action")
        self.save_button.remove_css_class("suggested-action")
        if self.save_state in {"ready", "error"} and self.save_button.get_sensitive():
            self.save_button.add_css_class("suggested-action")
        elif self.analyze_button.get_sensitive() and not self.is_busy():
            self.analyze_button.add_css_class("suggested-action")

    def set_analysis_action(
        self,
        label: str,
        accessible_label: str | None = None,
    ) -> None:
        self.analyze_button.set_label(label)
        self.analyze_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [accessible_label or label],
        )

    def update_analysis_action_label(
        self,
    ) -> None:
        if self.is_busy():
            return

        if self.analysis_retry_recommended:
            self.set_analysis_action(
                "Try Again",
                "Try the analysis again",
            )
            return

        if self.lyrics_path is None:
            self.set_analysis_action(
                "Generate Draft",
                "Generate an editable lyrics draft",
            )
        else:
            self.set_analysis_action(
                "Verify & Align",
                "Verify and align the selected lyrics",
            )

    def on_language_changed(
        self,
        _entry,
    ) -> None:
        self.language_example.set_visible(
            not bool(self.language_entry.get_text().strip())
        )
        if self.is_busy():
            return
        self.note_input_changed()
        self.reset_result()
        self.update_analysis_action_label()

    def mark_analysis_completed(
        self,
        *,
        retry_recommended: bool = False,
    ) -> None:
        # Completion belongs in status/result text, not in a temporary disabled
        # action label. Keep the next valid action immediately available.
        self.analysis_retry_recommended = retry_recommended
        self.update_analysis_action_label()
        self.analyze_button.set_sensitive(self.audio_path is not None)
        self.refresh_primary_action_style()

    @staticmethod
    def _clear_tone_classes(
        widget,
    ) -> None:
        for css_class in (
            "success",
            "warning",
            "error",
        ):
            widget.remove_css_class(
                css_class
            )

    def _set_tone(
        self,
        widget,
        tone: str | None,
    ) -> None:
        self._clear_tone_classes(
            widget
        )
        if tone in {
            "success",
            "warning",
            "error",
        }:
            widget.add_css_class(
                tone
            )

    def note_input_changed(
        self,
    ) -> None:
        self.input_generation += 1
        self.save_completed_generation = None
        self.analysis_retry_recommended = False

    def reset_save_state(
        self,
    ) -> None:
        self.save_state = "unavailable"
        if hasattr(self, "review_check"):
            self.setting_preview = True
            try:
                self.review_check.set_active(False)
                self.review_check.set_visible(False)
                self.review_check.set_sensitive(True)
                self.preview_view.set_editable(True)
                self.preview_view.set_cursor_visible(True)
            finally:
                self.setting_preview = False
        self.save_button.set_label(
            "Save LRC"
        )
        self.save_button.set_sensitive(
            False
        )
        self.save_button.remove_css_class(
            "suggested-action"
        )
        self._clear_tone_classes(
            self.save_button
        )
        self.save_feedback.set_text(
            ""
        )
        self.save_feedback.set_visible(
            False
        )
        self.save_feedback.remove_css_class(
            "dimmed"
        )
        self._clear_tone_classes(
            self.save_feedback
        )
        self.refresh_primary_action_style()

    def set_save_ready(
        self,
    ) -> None:
        if (
            self.save_completed_generation
            == self.input_generation
        ):
            self.set_save_completed(
                output=None,
                backup=None,
                preserve_generation=True,
            )
            return

        self.save_state = "ready"
        self.save_button.set_label(
            "Save LRC"
        )
        self.save_button.set_sensitive(
            True
        )
        self._clear_tone_classes(
            self.save_button
        )
        self.save_feedback.set_text(
            ""
        )
        self.save_feedback.set_visible(
            False
        )
        self.save_feedback.remove_css_class(
            "dimmed"
        )
        self._clear_tone_classes(
            self.save_feedback
        )
        self.refresh_primary_action_style()

    def set_save_locked(
        self,
        reason: str,
    ) -> None:
        self.save_state = "locked"
        self.save_button.set_label(
            "Save LRC"
        )
        self.save_button.set_sensitive(
            False
        )
        self.save_button.remove_css_class(
            "suggested-action"
        )
        self._clear_tone_classes(
            self.save_button
        )
        self.save_feedback.remove_css_class(
            "dimmed"
        )
        self.save_feedback.set_text(
            reason
        )
        self.save_feedback.set_visible(
            True
        )
        self._set_tone(
            self.save_feedback,
            "warning",
        )
        self.refresh_primary_action_style()

    def set_save_completed(
        self,
        *,
        output: Path | None,
        backup: Path | None,
        preserve_generation: bool = False,
    ) -> None:
        self.save_state = "completed"
        if not preserve_generation:
            self.save_completed_generation = (
                self.input_generation
            )
        self.output_allowed = False
        self.save_button.set_label(
            "Save LRC"
        )
        self.review_check.set_sensitive(False)
        self.preview_view.set_editable(False)
        self.preview_view.set_cursor_visible(False)
        self.save_button.set_sensitive(
            False
        )
        self.save_button.remove_css_class(
            "suggested-action"
        )
        self._clear_tone_classes(
            self.save_button
        )

        if output is None:
            message = "Already saved for these source files"
        elif backup is not None:
            message = "Saved Previous LRC backed up"
        else:
            message = "Saved"

        self.save_feedback.remove_css_class(
            "dimmed"
        )
        self.save_feedback.set_text(
            message
        )
        self.save_feedback.set_visible(
            True
        )
        self._set_tone(
            self.save_feedback,
            "success",
        )
        self.refresh_primary_action_style()

    def set_save_error(
        self,
        reason: str,
    ) -> None:
        self.save_state = "error"
        self.save_button.set_label(
            "Try Again"
        )
        self.save_button.set_sensitive(
            True
        )
        self._clear_tone_classes(
            self.save_button
        )
        self.save_feedback.remove_css_class(
            "dimmed"
        )
        self.save_feedback.set_text(
            "Could not save the LRC: " + reason
        )
        self.save_feedback.set_visible(
            True
        )
        self._set_tone(
            self.save_feedback,
            "error",
        )
        self.refresh_primary_action_style()

    def apply_theme(
        self,
        theme: str,
    ) -> None:
        if theme not in THEME_IDS:
            theme = DEFAULT_THEME

        self.current_theme = theme
        expected_state = GLib.Variant.new_string(theme)
        if self.theme_action.get_state().get_string() != theme:
            self.theme_action.set_state(expected_state)

        manager = self.style_manager
        if theme == "system":
            manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        elif theme == "light":
            manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        self.css_errors.clear()
        self.css_provider.load_from_string(css_for())
        self.timestamp_tag.set_property("foreground-set", False)

        store_theme(theme)

    def on_theme_action_changed(
        self,
        action,
        value,
    ) -> None:
        theme = value.get_string()
        if theme not in THEME_IDS:
            return
        action.set_state(value)
        self.apply_theme(theme)

    def on_high_contrast_changed(
        self,
        _manager,
        _param,
    ) -> None:
        self.apply_theme(self.current_theme)

    def set_report(
        self,
        text: str,
    ):
        self.report_view.get_buffer().set_text(
            text
        )
        has_report = bool(
            text.strip()
        )
        self.report_frame.set_visible(
            has_report
        )
        self.technical_expander.set_visible(
            has_report
        )
        if not has_report:
            self.technical_expander.set_expanded(
                False
            )

    def set_verification_result(
        self,
        result: dict,
    ) -> None:
        kind = result.get("kind", "unknown")
        self._clear_tone_classes(self.verification_state)
        self._clear_tone_classes(self.verification_icon)

        if kind == "aligned":
            confidence = int(
                round(float(result.get("confidence") or 0.0) * 100.0)
            )
            anchors = int(result.get("strong_matches") or result.get("direct_anchors") or 0)
            support = int(result.get("support_matches") or result.get("model_anchors") or 0)
            retimed = int(result.get("retimed_lines") or result.get("source_adjusted") or 0)
            total = int(result.get("total") or 0)
            review = int(result.get("review_count") or result.get("suspicious_count") or 0)

            self.metrics_row.set_visible(True)
            self.confidence_value.set_text(f"{confidence}%")
            self.anchors_value.set_text(f"{anchors} / {total}")
            self.review_value.set_text(str(review))

            summary = (
                f"{anchors} strong · {support} supporting · "
                f"{retimed} retimed · {review} need review"
            )

            if result.get("allowed", False):
                self.verification_icon.set_from_icon_name("emblem-ok-symbolic")
                self.verification_state.set_text("Timing repaired")
                self.verification_note.set_text(
                    summary
                    + ". Review the preview, then save the LRC once."
                )
                self._set_tone(self.verification_state, "success")
                self._set_tone(self.verification_icon, "success")
            else:
                self.verification_icon.set_from_icon_name("dialog-warning-symbolic")
                self.verification_state.set_text("Review required")
                self.verification_note.set_text(
                    summary
                    + ". Automatic approval was withheld; the preview can "
                    "still be reviewed and edited."
                )
                self._set_tone(self.verification_state, "warning")
                self._set_tone(self.verification_icon, "warning")

        elif kind == "generated":
            self.metrics_row.set_visible(False)
            self.verification_icon.set_from_icon_name("document-edit-symbolic")
            self.verification_state.set_text("Unverified draft ready")
            self.verification_note.set_text(
                "Whisper created an unverified ASR draft, not authoritative lyrics. "
                "Review and correct every word and timestamp before saving."
            )
            self._set_tone(self.verification_state, "warning")
            self._set_tone(self.verification_icon, "warning")

        elif kind == "generated-review":
            self.metrics_row.set_visible(False)
            self.verification_icon.set_from_icon_name("dialog-warning-symbolic")
            self.verification_state.set_text("Draft needs review")
            self.verification_note.set_text(
                "The ASR output looks repetitive or too uncertain for automatic approval. "
                "Review and correct the editable preview before confirming a save."
            )
            self._set_tone(self.verification_state, "warning")
            self._set_tone(self.verification_icon, "warning")

        elif kind == "generated-empty":
            self.metrics_row.set_visible(False)
            self.verification_icon.set_from_icon_name("dialog-warning-symbolic")
            self.verification_state.set_text("No reliable lyrics")
            self.verification_note.set_text(
                "No plausible sung or spoken lyric text was detected, "
                "so no savable LRC was created."
            )
            self._set_tone(self.verification_state, "warning")
            self._set_tone(self.verification_icon, "warning")

        else:
            self.metrics_row.set_visible(False)
            self.verification_icon.set_from_icon_name("dialog-information-symbolic")
            self.verification_state.set_text("Analysis complete")
            self.verification_note.set_text("Review the result below.")

    def set_verification_error(
        self,
        reason: str,
    ) -> None:
        self.metrics_row.set_visible(False)
        self.verification_icon.set_from_icon_name("dialog-error-symbolic")
        self.verification_state.set_text("Analysis failed")
        self.verification_note.set_text(reason)
        self._set_tone(self.verification_state, "error")
        self._set_tone(self.verification_icon, "error")

    def get_preview_text(
        self,
    ) -> str:
        buffer = self.preview_view.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, False)

    def on_preview_changed(
        self,
        _buffer,
    ) -> None:
        if self.setting_preview:
            return

        self.output_text = self.get_preview_text()

        self.setting_preview = True
        try:
            self.review_check.set_active(False)
        finally:
            self.setting_preview = False

        if self.output_text.strip():
            self.set_save_locked(
                "Preview changed. Review the complete LRC, then confirm it below."
            )
        else:
            self.reset_save_state()

    def on_review_toggled(
        self,
        button,
    ) -> None:
        if self.setting_preview:
            return

        if not button.get_active():
            if self.get_preview_text().strip():
                self.set_save_locked(
                    "Review the editable preview, then confirm it before saving."
                )
            return

        try:
            rows = parse_reviewed_lrc(self.get_preview_text())
        except VerseLatchError as exc:
            self.set_save_locked(
                "Review confirmation cannot unlock saving: " + str(exc)
            )
            return

        self.output_text = render_lrc(rows)
        self.set_save_ready()

    def set_preview(
        self,
        text: str,
    ):
        buffer = self.preview_view.get_buffer()
        self.setting_preview = True
        try:
            buffer.set_text("")

            for raw_line in text.splitlines():
                match = re.match(
                    r"^(\[[0-9]{1,3}:[0-9]{1,2}(?:[.:][0-9]{1,3})?\])(.*)$",
                    raw_line,
                )

                if match:
                    end = buffer.get_end_iter()
                    timestamp_text = match.group(1)
                    start_offset = buffer.get_char_count()
                    buffer.insert(end, timestamp_text)
                    tag_start = buffer.get_iter_at_offset(start_offset)
                    tag_end = buffer.get_end_iter()
                    buffer.apply_tag(
                        self.timestamp_tag,
                        tag_start,
                        tag_end,
                    )
                    end = buffer.get_end_iter()
                    lyric = match.group(2).lstrip()
                    buffer.insert(
                        end,
                        ("  " + lyric if lyric else "") + "\n",
                    )
                else:
                    end = buffer.get_end_iter()
                    buffer.insert(end, raw_line + "\n")

            self.review_check.set_active(False)
            self.review_check.set_visible(bool(text.strip()))
            self.review_check.set_sensitive(True)
            self.preview_view.set_editable(True)
            self.preview_view.set_cursor_visible(True)
        finally:
            self.setting_preview = False

    def choose_audio(
        self,
        _button,
    ):
        self.open_local_file_dialog(
            title="Open Audio",
            filter_name=(
                "FLAC / MP3 / OGG / WAV"
            ),
            patterns=(
                "*.flac",
                "*.FLAC",
                "*.mp3",
                "*.MP3",
                "*.ogg",
                "*.OGG",
                "*.wav",
                "*.WAV",
            ),
            callback=self.audio_chosen,
        )

    def open_local_file_dialog(
        self,
        *,
        title: str,
        filter_name: str,
        patterns: tuple[str, ...],
        callback,
    ) -> None:
        dialog = Gtk.FileDialog(
            title=title
        )

        file_filter = Gtk.FileFilter()

        file_filter.set_name(
            filter_name
        )

        for pattern in patterns:
            file_filter.add_pattern(
                pattern
            )

        filters = Gio.ListStore.new(
            Gtk.FileFilter
        )

        filters.append(
            file_filter
        )

        dialog.set_filters(
            filters
        )

        dialog.set_default_filter(
            file_filter
        )

        dialog.open(
            self,
            None,
            callback,
        )

    def audio_chosen(
        self,
        dialog: Gtk.FileDialog,
        result,
    ):
        try:
            selected = dialog.open_finish(
                result
            )
        except GLib.Error:
            return

        path = selected.get_path()

        if path is None:
            self.set_status(
                "Only files on this device are supported."
            )
            return

        self.load_audio(
            Path(path)
        )

    def choose_lyrics(
        self,
        _button,
    ):
        self.open_local_file_dialog(
            title="Open Lyrics",
            filter_name="LRC / TXT",
            patterns=(
                "*.lrc",
                "*.LRC",
                "*.lrc.bak-*",
                "*.LRC.bak-*",
                "*.txt",
                "*.TXT",
            ),
            callback=self.lyrics_chosen,
        )

    def lyrics_chosen(
        self,
        dialog: Gtk.FileDialog,
        result,
    ):
        try:
            selected = dialog.open_finish(
                result
            )
        except GLib.Error:
            return

        path = selected.get_path()

        if path is None:
            self.set_status(
                "Only files on this device are supported."
            )
            return

        try:
            candidate = resolve_lyrics_selection(path)
        except VerseLatchError as exc:
            self.set_status(
                str(exc)
            )
            return

        self.lyrics_path = candidate

        self.lyrics_row.set_subtitle(candidate.name)
        self.lyrics_row.set_tooltip_text(str(candidate))

        self.clear_button.set_visible(
            True
        )
        self.clear_button.set_sensitive(
            True
        )

        self.note_input_changed()
        self.reset_result()
        self.update_analysis_action_label()

        self.set_status(
            "Ready to verify and align"
        )

    def load_audio(
        self,
        path: Path,
    ):
        try:
            path = resolve_audio_selection(path)
        except VerseLatchError as exc:
            self.set_status(str(exc))
            return

        self.audio_path = path
        self.audio_row.set_subtitle(path.name)
        self.audio_row.set_tooltip_text(str(path))

        self.lyrics_path = None

        lrc = path.with_suffix(
            ".lrc"
        )

        txt = path.with_suffix(
            ".txt"
        )

        if lrc.is_file() and not lrc.is_symlink():
            self.lyrics_path = lrc

        elif txt.is_file() and not txt.is_symlink():
            self.lyrics_path = txt

        if self.lyrics_path:
            self.lyrics_row.set_subtitle(self.lyrics_path.name)
            self.lyrics_row.set_tooltip_text(str(self.lyrics_path))

            self.clear_button.set_visible(
                True
            )
            self.clear_button.set_sensitive(
                True
            )

            self.set_status(
                "Ready to verify and align"
            )

        else:
            self.lyrics_row.set_subtitle("Optional — no file selected")
            self.lyrics_row.set_tooltip_text(None)

            self.clear_button.set_visible(
                False
            )
            self.clear_button.set_sensitive(
                False
            )

            self.set_status(
                "Ready to generate a draft"
            )

        self.note_input_changed()
        self.reset_result()
        self.update_analysis_action_label()

        self.analyze_button.set_sensitive(
            True
        )
        self.refresh_primary_action_style()

    def clear_lyrics(
        self,
        _button,
    ):
        if self.is_busy():
            return

        self.lyrics_path = None

        self.lyrics_row.set_subtitle("Optional — no file selected")
        self.lyrics_row.set_tooltip_text(None)

        self.clear_button.set_visible(
            False
        )
        self.clear_button.set_sensitive(
            False
        )

        self.note_input_changed()
        self.reset_result()
        self.update_analysis_action_label()
        self.refresh_primary_action_style()

    def reset_result(
        self,
    ):
        self.output_text = ""
        self.output_allowed = False
        self.analyzed_audio_path = None
        self.analyzed_audio_state = None
        self.analyzed_lyrics_path = None
        self.analyzed_lyrics_state = None
        self.analysis_retry_recommended = False

        self.results_group.set_visible(
            False
        )
        self.preview_card.set_visible(
            False
        )
        self.set_report("")
        self.technical_expander.set_expanded(False)
        self.set_preview("")
        self.reset_save_state()

    def is_busy(
        self,
    ) -> bool:
        with self.process_lock:
            return self.analysis_active

    def set_busy(
        self,
        busy: bool,
    ):
        self.audio_button.set_sensitive(
            not busy
        )

        self.lyrics_button.set_sensitive(
            not busy
        )

        self.language_entry.set_sensitive(
            not busy
        )
        self.language_example.set_visible(
            not busy and not bool(self.language_entry.get_text().strip())
        )

        self.clear_button.set_sensitive(
            (
                not busy
                and self.lyrics_path
                is not None
            )
        )

        self.analyze_button.set_sensitive(
            (
                not busy
                and self.audio_path
                is not None
            )
        )

        self.cancel_button.set_visible(busy)
        self.cancel_button.set_sensitive(busy)

        if busy:
            self.set_analysis_action(
                "Generating…" if self.lyrics_path is None else "Aligning…",
                "Analysis in progress",
            )
        else:
            self.update_analysis_action_label()

        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()

        self.refresh_primary_action_style()

    def cancel_analysis(
        self,
        _button,
    ) -> None:
        if not self.is_busy() or self.analysis_cancel.is_set():
            return

        self.analysis_cancel.set()
        self.cancel_button.set_sensitive(False)
        self.set_status(
            "Cancelling analysis… No LRC will be written."
        )
        LOGGER.info("analysis cancellation requested by user")

        threading.Thread(
            target=self.terminate_analysis,
            daemon=True,
            name="verselatch-cancel",
        ).start()

    def start_analysis(
        self,
        _button,
    ):
        if (
            self.audio_path is None
            or self.is_busy()
        ):
            return

        try:
            language = normalize_language_hint(
                self.language_entry.get_text()
            )
        except VerseLatchError as exc:
            self.set_status(str(exc))
            return

        memory = available_memory_mib()

        required_memory = MIN_AVAILABLE_MEMORY_MIB

        if memory < required_memory:
            self.set_status(
                f"Only {memory} MiB memory is currently available; "
                f"this operation requires at least {required_memory} MiB free. "
                "Close heavy applications and try again."
            )
            return

        if WHISPER_CLI is None:
            self.set_status(
                "whisper-cli is not installed."
            )
            return

        if PRLIMIT is None:
            self.set_status(
                "prlimit is not installed."
            )
            return

        try:
            validate_model_file()
        except VerseLatchError:
            self.set_status(
                "Whisper Large v3 Turbo model is missing or invalid."
            )
            return

        self.reset_result()

        self.analysis_cancel.clear()

        with self.process_lock:
            if self.analysis_active:
                return

            self.analysis_active = True
            self.analysis_run_id += 1
            analysis_run_id = self.analysis_run_id

        self.set_busy(
            True
        )

        self.set_status(
            (
                "Generating an unverified lyrics draft. "
                if self.lyrics_path is None
                else "Verifying and aligning. "
            )
            + "Analysis runs locally and can take several minutes on CPU"
        )

        audio = self.audio_path
        lyrics = self.lyrics_path

        LOGGER.info(
            "analysis requested audio=%s mode=%s language=%s available_memory_mib=%d",
            audio.name,
            "generate" if lyrics is None else "verify-align",
            language,
            memory,
        )

        thread = threading.Thread(
            target=self.analysis_worker,
            args=(
                analysis_run_id,
                audio,
                lyrics,
                language,
            ),
            daemon=True,
            name="verselatch-analysis",
        )

        with self.process_lock:
            self.analysis_thread = thread

        try:
            thread.start()
        except Exception:
            with self.process_lock:
                self.analysis_active = False
                self.analysis_thread = None
            self.set_busy(False)
            raise

    def run_whisper(
        self,
        audio: Path,
        *,
        language: str,
    ) -> tuple[list[dict], bool, tuple[int, int, int, int, int]]:
        memory = available_memory_mib()

        required_memory = MIN_AVAILABLE_MEMORY_MIB
        if memory < required_memory:
            raise VerseLatchError(
                "Available memory became too low before analysis."
            )

        if self.analysis_cancel.is_set():
            raise AnalysisCancelled()

        validate_model_file(
            verify_digest=True,
            cancel_event=self.analysis_cancel,
        )

        cache_key, audio_state = build_asr_cache_key(
            audio,
            language=language,
            cancel_event=self.analysis_cancel,
        )

        if self.analysis_cancel.is_set():
            raise AnalysisCancelled()

        cached = load_asr_cache(cache_key)
        if cached is not None:
            LOGGER.info(
                "analysis cache hit audio=%s language=%s segments=%d",
                audio.name,
                language,
                len(cached),
            )
            return cached, True, audio_state

        with tempfile.TemporaryDirectory(
            prefix="verselatch-"
        ) as directory:
            prefix = Path(directory) / "result"

            command = [
                WHISPER_CLI,
                "-m",
                str(ASR_MODEL_PATH),
                "-f",
                str(audio),
                "-t",
                str(ASR_THREADS),
                "-p",
                "1",
                "-l",
                language,
                "-ml",
                str(ASR_MAX_SEGMENT_CHARS),
                "-sow",
                "-sns",
            ]

            command.extend(
                [
                    "-ojf",
                    "-of",
                    str(prefix),
                    "-np",
                ]
            )

            if PRLIMIT is None:
                raise VerseLatchError(
                    "Required prlimit tool is not installed."
                )
            command = [
                PRLIMIT,
                f"--fsize={MAX_WHISPER_OUTPUT_BYTES}",
                "--",
            ] + command

            nice = shutil.which("nice", path=SYSTEM_EXEC_PATH)
            if nice:
                command = [
                    nice,
                    "-n",
                    "10",
                ] + command

            env = native_tool_env(
                system_path=SYSTEM_EXEC_PATH,
                extra={
                    "OMP_NUM_THREADS": str(ASR_THREADS),
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                    "MALLOC_ARENA_MAX": "2",
                }
            )

            if self.analysis_cancel.is_set():
                raise AnalysisCancelled()

            with tempfile.TemporaryFile(
                mode="w+b",
                prefix="verselatch-whisper-stderr-",
            ) as stderr_file:
                LOGGER.info(
                    "whisper start audio=%s language=%s model=%s available_memory_mib=%d",
                    audio.name,
                    language,
                    ASR_MODEL_PATH.name,
                    available_memory_mib(),
                )

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_file,
                    env=env,
                    start_new_session=True,
                )

                with self.process_lock:
                    self.current_process = process

                if self.analysis_cancel.is_set():
                    terminate_process_group(process)

                try:
                    process.wait(timeout=1800)
                except subprocess.TimeoutExpired:
                    terminate_process_group(process)
                    raise VerseLatchError(
                        "Analysis exceeded the 30-minute timeout."
                    )
                finally:
                    with self.process_lock:
                        if self.current_process is process:
                            self.current_process = None

                if self.analysis_cancel.is_set():
                    raise AnalysisCancelled()

                LOGGER.info(
                    "whisper exit audio=%s language=%s returncode=%s",
                    audio.name,
                    language,
                    process.returncode,
                )

                if process.returncode != 0:
                    if process.returncode == -signal.SIGXFSZ:
                        raise VerseLatchError(
                            "Analysis output exceeded the 32 MiB safety limit."
                        )
                    message = tail_binary_file(stderr_file)
                    LOGGER.error(
                        "whisper failed audio=%s language=%s returncode=%s stderr_tail=%r",
                        audio.name,
                        language,
                        process.returncode,
                        message[-2000:],
                    )
                    raise VerseLatchError(
                        message
                        or (
                            "whisper-cli failed with exit code "
                            + str(process.returncode)
                            + "."
                        )
                    )

            json_path = Path(str(prefix) + ".json")
            if not json_path.is_file():
                raise VerseLatchError(
                    "Whisper did not create JSON output."
                )
            if json_path.stat().st_size > MAX_WHISPER_OUTPUT_BYTES:
                raise VerseLatchError(
                    "Whisper output exceeded the safety limit."
                )

            data = json.loads(
                json_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )
            segments = parse_whisper_json(data)

            if not segments:
                LOGGER.info(
                    "whisper produced no speech segments audio=%s language=%s",
                    audio.name,
                    language,
                )
                return [], False, audio_state

            try:
                current_state = regular_file_state(
                    audio,
                    description="Audio source",
                    maximum_bytes=MAX_AUDIO_BYTES,
                )
            except VerseLatchError as exc:
                raise VerseLatchError(
                    "Audio changed or became unsafe during analysis. Nothing was cached."
                ) from exc

            if current_state != audio_state:
                raise VerseLatchError(
                    "Audio changed during analysis. Nothing was cached."
                )

            store_asr_cache(cache_key, segments)
            return segments, False, audio_state

    def _run_aubio_detector(
        self,
        executable: str,
        audio: Path,
        *,
        timeout_seconds: int = 180,
    ) -> list[float]:
        if self.analysis_cancel.is_set():
            raise AnalysisCancelled()

        command = [
            executable,
            "-i",
            str(audio),
            "-T",
            "seconds",
        ]

        if PRLIMIT is None:
            raise VerseLatchError(
                "Required prlimit tool is not installed."
            )
        command = [
            PRLIMIT,
            f"--fsize={MAX_RHYTHM_OUTPUT_BYTES}",
            "--",
        ] + command

        nice = shutil.which("nice", path=SYSTEM_EXEC_PATH)
        if nice:
            command = [nice, "-n", "10"] + command

        env = native_tool_env(system_path=SYSTEM_EXEC_PATH)

        with (
            tempfile.TemporaryFile(
                mode="w+b",
                prefix="verselatch-aubio-stdout-",
            ) as stdout_file,
            tempfile.TemporaryFile(
                mode="w+b",
                prefix="verselatch-aubio-stderr-",
            ) as stderr_file,
        ):
            process = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
                start_new_session=True,
            )

            with self.process_lock:
                self.current_process = process

            if self.analysis_cancel.is_set():
                terminate_process_group(process)

            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                terminate_process_group(process)
                raise VerseLatchError(
                    "Rhythm analysis exceeded its safety timeout."
                )
            finally:
                with self.process_lock:
                    if self.current_process is process:
                        self.current_process = None

            if self.analysis_cancel.is_set():
                raise AnalysisCancelled()

            if process.returncode != 0:
                if process.returncode == -signal.SIGXFSZ:
                    raise VerseLatchError(
                        "Rhythm detector output exceeded the safety limit."
                    )
                detail = tail_binary_file(stderr_file)
                raise VerseLatchError(
                    detail
                    or f"{Path(executable).name} failed with exit code {process.returncode}."
                )

            stdout_file.flush()
            stdout_file.seek(0, os.SEEK_END)
            output_size = stdout_file.tell()

            if output_size > MAX_RHYTHM_OUTPUT_BYTES:
                raise VerseLatchError(
                    "Rhythm detector output exceeded the safety limit."
                )

            stdout_file.seek(0)
            text = stdout_file.read().decode(
                "utf-8",
                errors="replace",
            )

        return parse_aubio_times(text)

    def run_rhythm_analysis(
        self,
        audio: Path,
    ) -> dict | None:
        if AUBIOTRACK is None or AUBIOONSET is None:
            LOGGER.warning(
                "rhythm analysis unavailable: aubio CLI tools are missing"
            )
            return None

        try:
            beats = self._run_aubio_detector(
                AUBIOTRACK,
                audio,
            )
            onsets = self._run_aubio_detector(
                AUBIOONSET,
                audio,
            )
        except VerseLatchError:
            if self.analysis_cancel.is_set():
                raise
            LOGGER.exception(
                "rhythm analysis failed audio=%s",
                audio.name,
            )
            return None

        profile = summarize_rhythm(
            beats,
            onsets,
        )

        LOGGER.info(
            "rhythm analysis audio=%s bpm=%s beats=%d onsets=%d pulse=%s",
            audio.name,
            (
                f"{profile['bpm']:.1f}"
                if profile.get("bpm") is not None
                else "unresolved"
            ),
            profile["beats"],
            profile["onsets"],
            profile["regularity"],
        )

        return profile

    def analysis_worker(
        self,
        analysis_run_id: int,
        audio: Path,
        lyrics: Path | None,
        language: str,
    ):
        try:
            timing_source_note = "selected lyrics"
            recovered_backup: Path | None = None

            if lyrics is None:
                # Draft generation uses the configured multilingual ASR model.
                # It remains an ASR draft: automatic checks flag obvious repetition
                # and very-low-confidence output, while the editable preview keeps
                # the final decision explicit and human-reviewed.
                segments, cache_hit, audio_state = self.run_whisper(
                    audio,
                    language=language,
                )
                clean_segments, dropped_non_lyrics = sanitize_generated_segments(
                    segments
                )
                draft_quality = assess_generated_draft(clean_segments)
                asr_path = "full audio"
                model_label = "multilingual large-v3-turbo"
                lyric_entries = None
            else:
                lyrics_state_before = regular_file_state(
                    lyrics,
                    description="Lyrics source",
                    maximum_bytes=MAX_LYRICS_BYTES,
                )
                content = safe_read_text(lyrics)
                lyrics_source_state = regular_file_state(
                    lyrics,
                    description="Lyrics source",
                    maximum_bytes=MAX_LYRICS_BYTES,
                )
                if lyrics_source_state != lyrics_state_before:
                    raise VerseLatchError(
                        "Lyrics changed while they were being loaded; result was discarded."
                    )
                document = parse_lyric_document(content)
                lyric_entries = document["entries"]

                if not lyric_entries:
                    raise VerseLatchError(
                        "Lyrics file contains no usable text."
                    )

                source_was_suspicious = timing_pattern_is_suspicious(
                    lyric_entries
                )

                if source_was_suspicious:
                    lyric_entries, recovered_backup = recover_matching_backup_timing(
                        lyrics,
                        lyric_entries,
                    )
                    if recovered_backup is not None:
                        timing_source_note = "previous matching VerseLatch backup"
                    else:
                        timing_source_note = "selected lyrics (synthetic-looking timing)"

                segments, cache_hit, audio_state = self.run_whisper(
                    audio,
                    language=language,
                )
                asr_path = "full audio · word-aware segments"
                model_label = "multilingual large-v3-turbo"

            rhythm_profile = self.run_rhythm_analysis(audio)

            try:
                require_regular_file_state(
                    audio,
                    audio_state,
                    description="Audio source",
                    maximum_bytes=MAX_AUDIO_BYTES,
                )
            except VerseLatchError as exc:
                raise VerseLatchError(
                    "Audio changed or became unsafe before analysis completed; result was discarded."
                ) from exc

            if lyrics is not None:
                try:
                    require_regular_file_state(
                        lyrics,
                        lyrics_source_state,
                        description="Lyrics source",
                        maximum_bytes=MAX_LYRICS_BYTES,
                    )
                except VerseLatchError as exc:
                    raise VerseLatchError(
                        "Lyrics changed or became unsafe before analysis completed; result was discarded."
                    ) from exc

            if lyrics is None:
                rows = [
                    (
                        segment["start"],
                        segment["text"],
                    )
                    for segment in clean_segments
                ]
                preview = render_lrc(rows) if rows else ""

                report_lines = [
                    "MODE          UNVERIFIED DRAFT",
                    "ENGINE        whisper.cpp",
                    "ASR PATH      " + asr_path,
                    "MODEL         " + model_label,
                    "LANGUAGE      " + language,
                    f"THREADS       {ASR_THREADS}",
                    "ACCELERATION  automatic",
                    "NETWORK       none",
                    *rhythm_report_lines(rhythm_profile),
                    (
                        "CACHE         hit"
                        if cache_hit
                        else "CACHE         stored"
                    ),
                    "ASR SEGMENTS  " + str(len(segments)),
                    "LYRIC LINES   " + str(len(clean_segments)),
                    "FILTERED      " + str(dropped_non_lyrics),
                    "",
                ]

                confidence = draft_quality["weighted_confidence"]
                low_probability_fraction = draft_quality["low_probability_fraction"]
                report_lines.extend(
                    [
                        (
                            "TOKEN CONF    "
                            + (
                                f"{confidence * 100.0:.0f}%"
                                if confidence is not None
                                else "unavailable"
                            )
                        ),
                        (
                            "LOW-P TOKENS  "
                            + (
                                f"{low_probability_fraction * 100.0:.0f}%"
                                if low_probability_fraction is not None
                                else "unavailable"
                            )
                        ),
                        "REPETITION    " + str(draft_quality["severe_count"]),
                        (
                            "QUALITY       pass"
                            if draft_quality["safe"]
                            else "QUALITY       review required"
                        ),
                        "",
                    ]
                )

                if clean_segments and draft_quality["safe"]:
                    report_lines.extend(
                        [
                            "No lyric text was supplied.",
                            "Large v3 Turbo generated an unverified draft.",
                            "No spell-checking or language-model rewriting was applied.",
                            "Sung words can still be misheard; review and edit before saving.",
                        ]
                    )
                    status = "Completed. Review the draft before saving."
                    allowed = True
                    kind = "generated"
                elif clean_segments:
                    report_lines.extend(
                        [
                            "The transcription contains evidence of unreliable ASR output.",
                            "Automatic approval is withheld; the preview remains editable.",
                            "VerseLatch will not guess or spell-correct unsupported words.",
                        ]
                    )
                    for issue in draft_quality["severe"][:5]:
                        report_lines.append(
                            f"Segment {issue['index'] + 1}: {issue['reason']}"
                        )
                    if draft_quality["confidence_missing"]:
                        report_lines.append(
                            "Token-confidence evidence is unavailable; manual review is required."
                        )
                    elif draft_quality["confidence_failure"]:
                        report_lines.append(
                            "Token-confidence evidence is weak; manual review is required."
                        )
                    status = "Completed. Draft quality requires manual review."
                    allowed = False
                    kind = "generated-review"
                else:
                    report_lines.extend(
                        [
                            "No plausible sung or spoken lyric text was detected.",
                            "Non-speech captions are not exported as lyrics.",
                        ]
                    )
                    status = "Completed. No reliable lyric lines were detected."
                    allowed = False
                    kind = "generated-empty"

                result = {
                    "kind": kind,
                    "preview": preview,
                    "report": "\n".join(report_lines),
                    "allowed": allowed,
                    "status": status,
                    "audio_path": audio,
                    "audio_state": audio_state,
                    "lyrics_path": None,
                    "lyrics_state": None,
                }

            else:
                alignment = align_lyrics(
                    lyric_entries,
                    segments,
                )

                preview = render_lrc(alignment["rows"])
                suspicious = alignment["suspicious"]
                review_count = int(alignment["review_count"])

                timing_error = alignment["timing_median_error"]
                timing_error_text = (
                    f"{timing_error:.2f} s"
                    if math.isfinite(timing_error)
                    else "unresolved"
                )
                p90_error = alignment["timing_p90_error"]
                p90_error_text = (
                    f"{p90_error:.2f} s"
                    if math.isfinite(p90_error)
                    else "unresolved"
                )

                lines = [
                    "MODE          VERIFY + REPAIR",
                    "ENGINE        whisper.cpp",
                    "ASR PATH      " + asr_path,
                    "MODEL         " + model_label,
                    "LANGUAGE      " + language,
                    f"THREADS       {ASR_THREADS}",
                    "ACCELERATION  automatic",
                    "NETWORK       none",
                    *rhythm_report_lines(rhythm_profile),
                    (
                        "CACHE         hit"
                        if cache_hit
                        else "CACHE         stored"
                    ),
                    "TIMING SOURCE " + timing_source_note,
                    (
                        "CONFIDENCE    "
                        + str(round(alignment["confidence"] * 100))
                        + "%"
                    ),
                    (
                        "STRONG        "
                        + str(alignment["strong_matches"])
                        + " / "
                        + str(alignment["total"])
                    ),
                    (
                        "SUPPORT       "
                        + str(alignment["support_matches"])
                        + " / "
                        + str(alignment["total"])
                    ),
                    "MODEL ANCHORS " + str(alignment["model_anchors"]),
                    "RETIMED       " + str(alignment["retimed_lines"]),
                    "NEEDS REVIEW  " + str(review_count),
                    "TIMING MODEL  " + alignment["timing_model"],
                    "SCALE         " + f"{alignment['timing_scale']:.6f}",
                    "OFFSET        " + f"{alignment['timing_offset']:+.2f} s",
                    "MEDIAN ERROR  " + timing_error_text,
                    "P90 ERROR     " + p90_error_text,
                    (
                        "AUTO GATE     "
                        + ("pass" if alignment["safe"] else "review required")
                    ),
                    "WRITE STATUS  explicit preview review required",
                    "",
                    "Selected lyric words remain unchanged unless edited in the preview.",
                    "Source timing is preserved unless coherent ASR evidence "
                    "justifies a smooth correction.",
                    "ASR evidence is matched against bounded word windows, not whole long segments.",
                    "Unmatched lines are never filled with equal-gap interpolation.",
                ]

                if recovered_backup is not None:
                    lines.extend(
                        [
                            "",
                            "RECOVERY",
                            "Selected LRC matched the legacy synthetic-timing fingerprint.",
                            "Timing prior was recovered from: " + recovered_backup.name,
                            "Lyric words still come from the selected LRC.",
                        ]
                    )

                if suspicious:
                    lines.extend(
                        [
                            "",
                            "REVIEW EVIDENCE",
                        ]
                    )
                    for item in suspicious[:10]:
                        lines.extend(
                            [
                                "",
                                "Line:     " + item["expected"],
                                "Evidence: " + item["heard"],
                                "Reason:   " + item.get("reason", "weak evidence"),
                                "Match:    " + str(round(item["score"] * 100)) + "%",
                            ]
                        )

                if alignment["safe"]:
                    status = (
                        "Timing repair passed automatic checks; "
                        "human review is still required."
                    )
                elif not alignment["timing_coherent"]:
                    status = (
                        "Timing evidence is not coherent enough for automatic repair. "
                        "Source timing was preserved; review or edit the preview manually."
                    )
                elif alignment["synthetic_output"]:
                    status = (
                        "The timing pattern still looks synthetic. "
                        "Review or edit the preview manually."
                    )
                else:
                    status = (
                        "Some lines need review. The preview remains editable "
                        "for an explicit human decision."
                    )

                result = {
                    "kind": "aligned",
                    "preview": preview,
                    "report": "\n".join(lines),
                    "allowed": alignment["safe"],
                    "confidence": alignment["confidence"],
                    "anchors": alignment["model_anchors"],
                    "direct_anchors": alignment["strong_matches"],
                    "strong_matches": alignment["strong_matches"],
                    "support_matches": alignment["support_matches"],
                    "model_anchors": alignment["model_anchors"],
                    "source_adjusted": alignment["retimed_lines"],
                    "retimed_lines": alignment["retimed_lines"],
                    "total": alignment["total"],
                    "suspicious_count": review_count,
                    "review_count": review_count,
                    "timing_model": alignment["timing_model"],
                    "timing_median_error": alignment["timing_median_error"],
                    "timing_source": timing_source_note,
                    "status": status,
                    "audio_path": audio,
                    "audio_state": audio_state,
                    "lyrics_path": lyrics,
                    "lyrics_state": lyrics_source_state,
                }

            error = None

        except Exception as exc:
            cancelled = isinstance(exc, AnalysisCancelled)
            error = str(exc)
            if cancelled:
                LOGGER.info(
                    "analysis worker cancelled audio=%s run_id=%d",
                    audio.name,
                    analysis_run_id,
                )
            else:
                LOGGER.exception(
                    "analysis worker failed audio=%s run_id=%d",
                    audio.name,
                    analysis_run_id,
                )
            result = None
        else:
            cancelled = False

        finally:
            with self.process_lock:
                if analysis_run_id == self.analysis_run_id:
                    self.analysis_active = False
                    self.analysis_thread = None

        if not self.closing:
            GLib.idle_add(
                self.analysis_done,
                analysis_run_id,
                result,
                error,
                cancelled,
            )

    def analysis_done(
        self,
        analysis_run_id: int,
        result,
        error,
        cancelled: bool,
    ):
        if self.closing or analysis_run_id != self.analysis_run_id:
            LOGGER.info(
                "discarded stale analysis callback run_id=%d current_run_id=%d",
                analysis_run_id,
                self.analysis_run_id,
            )
            return False

        self.set_busy(False)

        if cancelled:
            self.output_text = ""
            self.output_allowed = False
            self.analyzed_audio_path = None
            self.analyzed_audio_state = None
            self.analyzed_lyrics_path = None
            self.analyzed_lyrics_state = None
            self.analysis_retry_recommended = False
            self.results_group.set_visible(False)
            self.preview_card.set_visible(False)
            self.set_report("")
            self.set_preview("")
            self.reset_save_state()
            self.set_status(
                "Analysis cancelled. No LRC was written."
            )
            self.update_analysis_action_label()
            self.analyze_button.set_sensitive(self.audio_path is not None)
            self.refresh_primary_action_style()
            LOGGER.info("analysis cancelled cleanly")
            return False

        self.results_group.set_visible(True)

        if error:
            self.output_text = ""
            self.output_allowed = False
            self.analyzed_audio_path = None
            self.analyzed_audio_state = None
            self.analyzed_lyrics_path = None
            self.analyzed_lyrics_state = None
            self.analysis_retry_recommended = True
            self.set_status("Analysis failed. Try again.")
            self.set_report(error)
            self.set_verification_error(error)
            self.set_preview("")
            self.preview_card.set_visible(False)
            self.reset_save_state()
            self.update_analysis_action_label()
            self.analyze_button.set_sensitive(self.audio_path is not None)
            self.refresh_primary_action_style()
            return False

        self.output_text = result["preview"]
        self.output_allowed = bool(result["allowed"])
        self.analyzed_audio_path = result.get("audio_path")
        self.analyzed_audio_state = result.get("audio_state")
        self.analyzed_lyrics_path = result.get("lyrics_path")
        self.analyzed_lyrics_state = result.get("lyrics_state")
        if result.get("kind") == "aligned":
            if result.get("allowed", False):
                friendly_status = (
                    "Finished — automatic timing checks passed. Review the editable preview."
                )
            else:
                friendly_status = (
                    "Finished — automatic checks need human review. The preview remains editable."
                )
        elif result.get("kind") == "generated":
            friendly_status = "Finished — review and correct the generated draft."
        elif result.get("kind") == "generated-review":
            friendly_status = (
                "Finished — automatic draft checks were uncertain. "
                "Review and correct it manually."
            )
        elif result.get("kind") == "generated-empty":
            friendly_status = "Finished — no reliable lyric lines were detected."
        else:
            friendly_status = result.get("status", "Analysis finished.")

        self.set_status(friendly_status)
        self.technical_expander.set_expanded(False)
        self.set_report(result["report"])
        self.set_verification_result(result)
        self.set_preview(result["preview"])
        self.preview_card.set_visible(bool(result["preview"]))

        if result["preview"]:
            if self.output_allowed:
                reason = (
                    "Automatic checks passed. Review the editable preview, then confirm it "
                    "before saving."
                )
            elif result.get("kind") == "generated-review":
                reason = (
                    "Automatic draft checks did not pass. Correct any wrong words or timestamps, "
                    "review the complete preview, then confirm it to save intentionally."
                )
            elif result.get("kind") == "aligned":
                reason = (
                    "Automatic alignment checks did not pass. Source text/timing was preserved "
                    "where evidence was insufficient; review or edit the preview, then confirm it."
                )
            else:
                reason = (
                    "Review the editable preview, then confirm it before saving."
                )
            self.set_save_locked(reason)
        else:
            self.reset_save_state()

        retry_recommended = not bool(result.get("preview"))
        LOGGER.info(
            "analysis complete kind=%s automatic_gate_pass=%s preview_available=%s",
            result.get("kind", "unknown"),
            self.output_allowed,
            bool(result.get("preview")),
        )
        self.mark_analysis_completed(
            retry_recommended=retry_recommended,
        )
        return False

    def save_result(
        self,
        _button,
    ):
        if (
            self.audio_path is None
            or not self.review_check.get_active()
            or self.save_state not in {"ready", "error"}
        ):
            return

        try:
            reviewed_rows = parse_reviewed_lrc(self.get_preview_text())
            reviewed_text = render_lrc(reviewed_rows)
        except VerseLatchError as exc:
            self.set_save_error(str(exc))
            return

        self.save_state = "saving"
        self.save_button.set_label("Saving…")
        self.save_button.set_sensitive(False)
        self.refresh_primary_action_style()
        self.save_feedback.remove_css_class("dimmed")
        self.save_feedback.set_text("Saving…")
        self.save_feedback.set_visible(True)
        self._clear_tone_classes(self.save_feedback)
        self.save_feedback.add_css_class("dimmed")

        try:
            output, backup = safe_write_reviewed_lrc(
                content=reviewed_text,
                current_audio_path=self.audio_path,
                analyzed_audio_path=self.analyzed_audio_path,
                analyzed_audio_state=self.analyzed_audio_state,
                current_lyrics_path=self.lyrics_path,
                analyzed_lyrics_path=self.analyzed_lyrics_path,
                analyzed_lyrics_state=self.analyzed_lyrics_state,
                maximum_audio_bytes=MAX_AUDIO_BYTES,
                maximum_lyrics_bytes=MAX_LYRICS_BYTES,
            )
            self.output_text = reviewed_text

            self.lyrics_path = output
            self.lyrics_row.set_subtitle(output.name)
            self.lyrics_row.set_tooltip_text(str(output))
            self.clear_button.set_visible(True)
            self.clear_button.set_sensitive(True)

            LOGGER.info(
                "lrc saved output=%s backup_created=%s",
                output.name,
                backup is not None,
            )
            self.set_status("LRC saved")
            self.set_save_completed(
                output=output,
                backup=backup,
            )

        except Exception as exc:
            LOGGER.exception(
                "lrc save failed audio=%s",
                self.audio_path.name,
            )
            reason = str(exc).strip() or exc.__class__.__name__
            self.set_status("LRC could not be saved.")
            self.set_save_error(reason)

    def shutdown_runtime(
        self,
    ) -> None:
        if self.closing:
            return

        self.closing = True
        self.analysis_cancel.set()
        LOGGER.info("shutdown requested")
        self.terminate_analysis()

    def terminate_analysis(
        self,
    ):
        self.analysis_cancel.set()

        with self.process_lock:
            process = self.current_process

        if (
            process is not None
            and process.poll() is None
        ):
            terminate_process_group(
                process
            )

    def finish_pending_close(
        self,
    ):
        if self.is_busy():
            return GLib.SOURCE_CONTINUE

        self.force_close = True
        self.close()

        return GLib.SOURCE_REMOVE

    def on_close_request(
        self,
        _window,
    ):
        if self.force_close:
            return False

        self.shutdown_runtime()

        if self.is_busy():

            if not self.close_pending:
                self.close_pending = True

                GLib.timeout_add(
                    50,
                    self.finish_pending_close,
                )

            return True

        return False


class VerseLatchApplication(
    Adw.Application
):
    def __init__(
        self,
        *,
        smoke_test: bool = False,
    ):
        super().__init__(
            application_id=APP_ID,
            flags=(
                Gio.ApplicationFlags.NON_UNIQUE
                if smoke_test
                else Gio.ApplicationFlags.DEFAULT_FLAGS
            ),
        )

        self.window = None
        self.smoke_test = smoke_test
        self.smoke_test_errors: list[str] = []
        self.smoke_test_scheduled = False

        self.connect(
            "shutdown",
            self.on_application_shutdown,
        )

    def on_application_shutdown(
        self,
        _application,
    ) -> None:
        if self.window is None:
            return

        self.window.shutdown_runtime()

        with self.window.process_lock:
            thread = self.window.analysis_thread

        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout=6.0)

        LOGGER.info(
            "application shutdown analysis_thread_alive=%s",
            bool(thread is not None and thread.is_alive()),
        )

    def do_activate(
        self,
    ):
        if self.window is None:
            self.window = MainWindow(
                self
            )

        self.window.present()

        if (
            self.smoke_test
            and not self.smoke_test_scheduled
        ):
            self.smoke_test_scheduled = True

            # Exercise the post-analysis UI as part of the smoke gate, not
            # only the empty startup state. All text is fictional.
            self.window.results_group.set_visible(True)
            self.window.preview_card.set_visible(True)
            smoke_result = {
                "kind": "aligned",
                "allowed": True,
                "confidence": 0.96,
                "anchors": 4,
                "total": 4,
                "suspicious_count": 0,
            }
            if not self.window.language_example.get_visible():
                self.smoke_test_errors.append(
                    "Language-code example must be visible while the field is empty."
                )

            self.window.set_report(
                "MODE          VERIFY + RETIME\n"
                "ENGINE        whisper.cpp\n"
                "MODEL         multilingual large-v3-turbo\n"
                f"THREADS       {ASR_THREADS}\n"
                "ACCELERATION  automatic\n"
                "NETWORK       none\n"
                "CACHE         hit\n"
                "CONFIDENCE    96%\n"
                "ANCHORS       4 / 4\n"
                "SUSPICIOUS    0\n"
                "WRITE STATUS  manual save allowed\n"
                "\nSUSPICIOUS TEXT EVIDENCE\n"
            )
            self.window.language_entry.set_text("tr")
            if self.window.language_example.get_visible():
                self.smoke_test_errors.append(
                    "Language-code example must hide after the user enters a code."
                )
            self.window.set_verification_result(smoke_result)
            self.window.set_preview(
                "[00:01.00]silver morning\n"
                "[00:04.00]quiet satellite\n"
            )
            self.window.review_check.set_active(True)
            self.window.mark_analysis_completed()

            GLib.timeout_add(
                900,
                self.finish_smoke_test,
            )

    def finish_smoke_test(
        self,
    ):
        if self.window is not None:
            self.smoke_test_errors.extend(
                self.window.css_errors
            )

            if not isinstance(self.window.audio_row, Adw.ActionRow):
                self.smoke_test_errors.append(
                    "Audio source must use the native ActionRow pattern."
                )

            if not isinstance(self.window.lyrics_row, Adw.ActionRow):
                self.smoke_test_errors.append(
                    "Lyrics source must use the native ActionRow pattern."
                )

            if self.window.clear_button.get_visible():
                self.smoke_test_errors.append(
                    "Clear action must stay hidden until lyrics exist."
                )

            if self.window.cancel_button.get_visible():
                self.smoke_test_errors.append(
                    "Cancel action must stay hidden while analysis is idle."
                )

            if not self.window.review_check.get_active():
                self.smoke_test_errors.append(
                    "Review confirmation must unlock the save workflow."
                )

            if self.window.save_state != "ready":
                self.smoke_test_errors.append(
                    "A valid reviewed preview must enter the ready-to-save state."
                )

            if not self.window.save_button.has_css_class("suggested-action"):
                self.smoke_test_errors.append(
                    "Ready-to-save preview must make Save LRC the suggested action."
                )
            if self.window.analyze_button.has_css_class("suggested-action"):
                self.smoke_test_errors.append(
                    "Only one suggested action may be visible in the ready state."
                )

            if self.window.save_button.get_label() != "Save LRC":
                self.smoke_test_errors.append(
                    "Generated output action must be labeled Save LRC."
                )

            if self.window.review_value.get_text() != "0":
                self.smoke_test_errors.append(
                    "Flagged metric must come from structured numeric data."
                )

            if self.window.technical_expander.get_expanded():
                self.smoke_test_errors.append(
                    "Technical details must be collapsed by default."
                )

            self.window.input_generation = 7
            self.window.set_save_completed(
                output=Path("song.lrc"),
                backup=None,
            )
            if self.window.save_button.get_label() != "Save LRC":
                self.smoke_test_errors.append(
                    "Successful save must keep the action label stable."
                )
            if not self.window.save_feedback.get_text().startswith("Saved"):
                self.smoke_test_errors.append(
                    "Successful save must report completion in status text."
                )
            if self.window.save_button.get_sensitive():
                self.smoke_test_errors.append(
                    "Completed save must not be clickable."
                )

            self.window.note_input_changed()
            self.window.reset_save_state()
            self.window.set_preview(
                "[00:02.00]paper horizon\n"
                "[00:05.00]distant lantern\n"
            )
            self.window.review_check.set_active(True)
            if self.window.save_button.get_label() != "Save LRC":
                self.smoke_test_errors.append(
                    "Changing source input must reset Save LRC."
                )
            if not self.window.save_button.get_sensitive():
                self.smoke_test_errors.append(
                    "Changed source input must allow a valid new save."
                )

            self.window.set_save_error("permission denied")
            if self.window.save_button.get_label() != "Try Again":
                self.smoke_test_errors.append(
                    "Failed save must expose Try Again."
                )
            if "permission denied" not in self.window.save_feedback.get_text():
                self.smoke_test_errors.append(
                    "Failed save must show the error reason inline."
                )

            if self.window.analyze_button.get_label() not in {"Generate Draft", "Verify & Align"}:
                self.smoke_test_errors.append(
                    "Successful analysis must keep a stable task action label."
                )

            self.window.close()

        self.quit()

        return GLib.SOURCE_REMOVE


def self_test():
    gtk_version = (
        Gtk.get_major_version(),
        Gtk.get_minor_version(),
    )

    adw_version = (
        Adw.get_major_version(),
        Adw.get_minor_version(),
    )

    assert gtk_version >= MIN_GTK_VERSION, (
        "GTK 4.16 or newer is required."
    )

    assert adw_version >= MIN_ADW_VERSION, (
        "libadwaita 1.8 or newer is required."
    )

    assert normalize(
        "We're HERE!"
    ) == "were here"

    source = (
        "[ar:Fictional Artist]\n"
        "[00:01.00]silver morning\n"
        "[00:11.00]quiet satellite\n"
        "[00:21.00]paper horizon\n"
        "[00:31.00]distant lantern\n"
    )

    document = parse_lyric_document(source)

    assert [
        item["text"]
        for item in document["entries"]
    ] == [
        "silver morning",
        "quiet satellite",
        "paper horizon",
        "distant lantern",
    ]
    assert [
        item["source_time"]
        for item in document["entries"]
    ] == [1.0, 11.0, 21.0, 31.0]

    segments = [
        {
            "start": 1.0,
            "end": 2.0,
            "text": "silver morning",
        },
        {
            "start": 11.0,
            "end": 12.0,
            "text": "quiet satellite",
        },
        {
            "start": 21.0,
            "end": 22.0,
            "text": "paper horizon",
        },
        {
            "start": 31.0,
            "end": 32.0,
            "text": "distant lantern",
        },
    ]

    result = align_lyrics(
        document["entries"],
        segments,
    )

    assert result["safe"]
    assert result["anchors"] == 4
    assert (
        result["confidence"]
        > 0.95
    )

    rendered = render_lrc(
        result["rows"]
    )

    assert (
        "[00:01.00]silver morning"
        in rendered
    )

    # Regression: the old equal-gap engine could emit every timestamp with
    # the same non-zero centisecond fraction. Detect that fingerprint and
    # verify a varied prior stays varied after smooth repair.
    synthetic = parse_lyric_document(
        "\n".join(
            [
                "[00:01.88]silver morning",
                "[00:04.88]quiet satellite",
                "[00:07.88]paper horizon",
                "[00:10.88]distant lantern",
                "[00:13.88]amber window",
                "[00:16.88]winter signal",
                "[00:19.88]soft horizon",
                "[00:22.88]open water",
                "[00:25.88]northbound echo",
                "[00:28.88]final lantern",
            ]
        )
    )["entries"]
    assert timing_pattern_is_suspicious(synthetic)

    natural = parse_lyric_document(
        "\n".join(
            [
                "[00:01.12]silver morning",
                "[00:08.31]quiet satellite",
                "[00:15.57]paper horizon",
                "[00:22.04]distant lantern",
                "[00:29.46]amber window",
                "[00:36.77]winter signal",
                "[00:43.09]soft horizon",
                "[00:50.63]open water",
                "[00:57.28]northbound echo",
                "[01:04.91]final lantern",
            ]
        )
    )["entries"]
    assert not timing_pattern_is_suspicious(natural)

    warp_segments = [
        {
            "start": 1.02 * float(item["source_time"]) + 0.20,
            "end": 1.02 * float(item["source_time"]) + 1.0,
            "text": item["text"],
        }
        for item in natural
    ]
    warp_result = align_lyrics(
        natural,
        warp_segments,
    )
    assert warp_result["safe"]
    assert warp_result["timing_model"] == "affine"
    assert abs(warp_result["timing_scale"] - 1.02) < 0.01
    assert not warp_result["synthetic_output"]
    assert len({
        int(round(start * 100.0)) % 100
        for start, _ in warp_result["rows"]
    }) > 3

    # Word-window mapping scalability and multi-line Whisper-segment
    # regressions are exercised by tests/test_alignment_core.py. Keep this
    # installed self-test on the public core API only.

    assert parse_reviewed_lrc(
        "[00:01.00] silver morning\n[00:04.25] quiet satellite\n"
    ) == [
        (1.0, "silver morning"),
        (4.25, "quiet satellite"),
    ]

    try:
        parse_reviewed_lrc(
            "[00:04.00] later line\n[00:03.00] earlier line\n"
        )
    except VerseLatchError:
        pass
    else:
        raise AssertionError(
            "Reviewed LRC accepted non-monotonic timestamps."
        )

    assert normalize_language_hint("") == "auto"
    assert normalize_language_hint(" TR ") == "tr"
    try:
        normalize_language_hint("not-a-language")
    except VerseLatchError:
        pass
    else:
        raise AssertionError("Unsupported language code was accepted.")

    parsed_asr = parse_whisper_json(
        {
            "transcription": [
                {
                    "text": "opening line",
                    "offsets": {
                        "from": 0,
                        "to": 750,
                    },
                },
                {
                    "text": " silver morning ",
                    "offsets": {
                        "from": 1000,
                        "to": 2000,
                    },
                }
            ]
        }
    )

    assert parsed_asr == [
        {
            "start": 0.0,
            "end": 0.75,
            "text": "opening line",
        },
        {
            "start": 1.0,
            "end": 2.0,
            "text": "silver morning",
        },
    ]

    timed_asr = parse_whisper_json(
        {
            "transcription": [
                {
                    "text": " silver morning",
                    "offsets": {"from": 1000, "to": 2200},
                    "tokens": [
                        {
                            "text": "[_BEG_]",
                            "p": 0.99,
                            "offsets": {"from": 1000, "to": 1000},
                        },
                        {
                            "text": " silver",
                            "p": 0.90,
                            "offsets": {"from": 1100, "to": 1500},
                        },
                        {
                            "text": " morning",
                            "p": 0.80,
                            "offsets": {"from": 1550, "to": 2100},
                        },
                    ],
                }
            ]
        }
    )
    assert timed_asr[0]["words"] == [
        {"text": "silver", "start": 1.1, "end": 1.5},
        {"text": "morning", "start": 1.55, "end": 2.1},
    ]
    assert abs(timed_asr[0]["token_confidence"] - 0.85) < 1e-6
    filtered_asr, dropped = sanitize_generated_segments(
        [
            {"start": 0.0, "end": 1.0, "text": "[MÜZİK ÇALIYOR]"},
            {"start": 1.0, "end": 2.0, "text": "[music]"},
            {"start": 2.0, "end": 3.0, "text": "silver morning"},
            {"start": 3.0, "end": 4.0, "text": "♪♫"},
        ]
    )
    assert dropped == 3
    assert filtered_asr == [
        {"start": 2.0, "end": 3.0, "text": "silver morning"}
    ]

    # Regression: a 30-second decoder loop must never become a savable
    # LRC merely because it contains alphabetic text. The fixture is fictional.
    runaway = {
        "start": 0.0,
        "end": 30.0,
        "text": "alpha beta gamma delta " * 12,
        "token_confidence": 0.62,
        "low_confidence_fraction": 0.10,
        "token_count": 48,
    }
    clean_line = {
        "start": 30.0,
        "end": 34.0,
        "text": "silver morning over quiet water",
        "token_confidence": 0.78,
        "low_confidence_fraction": 0.0,
        "token_count": 6,
    }
    quality = assess_generated_draft([runaway, clean_line])
    assert not quality["safe"]
    assert quality["severe_count"] == 1
    assert "repetition" in quality["severe"][0]["reason"]

    good_quality = assess_generated_draft([clean_line])
    assert good_quality["safe"]
    assert good_quality["severe_count"] == 0

    missing_probability = {
        "start": 0.0,
        "end": 3.0,
        "text": "quiet silver morning",
    }
    missing_quality = assess_generated_draft([missing_probability])
    assert not missing_quality["safe"]
    assert missing_quality["confidence_missing"]

    very_low = dict(clean_line)
    very_low["token_confidence"] = 0.10
    very_low["low_confidence_fraction"] = 0.90
    very_low["token_count"] = 12
    assert not assess_generated_draft([very_low])["safe"]

    parsed_probabilities = parse_whisper_json(
        {
            "transcription": [
                {
                    "text": "silver morning",
                    "offsets": {"from": 1000, "to": 2000},
                    "tokens": [
                        {"text": " silver", "p": 0.8},
                        {"text": " morning", "p": 0.6},
                        {"text": "<|endoftext|>", "p": 0.1},
                    ],
                }
            ]
        }
    )
    assert len(parsed_probabilities) == 1
    assert abs(parsed_probabilities[0]["token_confidence"] - 0.7) < 1e-6
    assert parsed_probabilities[0]["token_count"] == 2


    assert is_non_lyric_asr_text("[MÜZİK ÇALIYOR]")
    assert is_non_lyric_asr_text("♪ ♫")
    assert not is_non_lyric_asr_text("silver lantern")

    rhythm = summarize_rhythm(
        [
            0.5, 1.0, 1.5, 2.0, 2.5,
            3.0, 3.5, 4.0, 4.5, 5.0,
        ],
        [
            0.25, 0.5, 0.75, 1.0, 1.25,
            1.5, 1.75, 2.0, 2.25, 2.5,
            2.75, 3.0, 3.25, 3.5, 3.75,
            4.0, 4.25, 4.5, 4.75, 5.0,
        ],
    )
    assert rhythm["bpm"] is not None
    assert abs(rhythm["bpm"] - 120.0) < 0.01
    assert rhythm["regularity"] == "steady"
    assert rhythm["beats"] == 10
    assert rhythm["onsets"] == 20

    assert validate_asr_segments(
        [
            {
                "start": float("nan"),
                "end": 2.0,
                "text": "invalid",
            }
        ]
    ) is None

    with tempfile.TemporaryDirectory(
        prefix="verselatch-self-test-"
    ) as directory:
        audio = Path(directory) / "song.flac"
        output = Path(directory) / "song.lrc"

        audio.write_bytes(b"self-test")

        integrity_fixture = Path(directory) / "integrity.bin"
        integrity_fixture.write_bytes(b"VerseLatch integrity fixture\n")
        integrity_sha256 = hashlib.sha256(
            integrity_fixture.read_bytes()
        ).hexdigest()
        verified_fixture = _verify_regular_file_sha256(
            integrity_fixture,
            description="Integrity fixture",
            expected_size=integrity_fixture.stat().st_size,
            expected_sha256=integrity_sha256,
        )
        assert verified_fixture.st_size == integrity_fixture.stat().st_size
        try:
            _verify_regular_file_sha256(
                integrity_fixture,
                description="Integrity fixture",
                expected_size=integrity_fixture.stat().st_size,
                expected_sha256="0" * 64,
            )
        except VerseLatchError:
            pass
        else:
            raise AssertionError(
                "Integrity verification accepted the wrong SHA-256."
            )

        # App-owned private directories must refuse a symlink leaf instead
        # of chmod/pruning data in an unrelated target directory.
        private_victim = Path(directory) / "private-victim"
        private_victim.mkdir()
        private_victim.chmod(0o755)
        private_link = Path(directory) / "private-link"
        private_link.symlink_to(
            private_victim,
            target_is_directory=True,
        )
        try:
            _ensure_private_directory(private_link)
        except OSError:
            pass
        else:
            raise AssertionError(
                "Private directory helper accepted a symlink leaf."
            )
        assert stat.S_IMODE(private_victim.stat().st_mode) == 0o755

        # A lyrics symlink must be rejected before canonicalization.
        real_lyrics = Path(directory) / "real.txt"
        real_lyrics.write_text(
            "silver morning\n",
            encoding="utf-8",
        )
        linked_lyrics = Path(directory) / "linked.txt"
        linked_lyrics.symlink_to(real_lyrics)
        try:
            resolve_lyrics_selection(linked_lyrics)
        except VerseLatchError:
            pass
        else:
            raise AssertionError(
                "Lyrics selection accepted a symbolic link."
            )

        # Audio leaf symlinks are rejected before canonicalization so sidecar
        # output cannot unexpectedly move next to a symlink target.
        real_audio = Path(directory) / "real.flac"
        real_audio.write_bytes(b"audio")
        linked_audio_selection = Path(directory) / "audio-link.flac"
        linked_audio_selection.symlink_to(real_audio)
        try:
            resolve_audio_selection(linked_audio_selection)
        except VerseLatchError:
            pass
        else:
            raise AssertionError(
                "Audio selection accepted a symbolic link."
            )

        # Relative XDG paths are invalid and must fall back.
        old_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = "relative-cache"
        try:
            assert _xdg_base_directory(
                "XDG_CACHE_HOME",
                Path("/fallback-cache"),
            ) == Path("/fallback-cache")
        finally:
            if old_xdg is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old_xdg

        # Legacy timing recovery is text-bound and local.
        recovery_lrc = Path(directory) / "recovery.lrc"
        recovery_backup = Path(directory) / "recovery.lrc.bak-safe123"
        recovery_lines = [
            "silver morning",
            "quiet satellite",
            "paper horizon",
            "distant lantern",
            "amber window",
            "winter signal",
            "soft horizon",
            "open water",
            "northbound echo",
            "final lantern",
        ]
        recovery_lrc.write_text(
            "\n".join(
                f"[00:{1 + index * 3:02d}.88]{text}"
                for index, text in enumerate(recovery_lines)
            ) + "\n",
            encoding="utf-8",
        )
        recovery_backup.write_text(
            "\n".join(
                f"[00:{1 + index * 3:02d}.{(11 + index * 7) % 100:02d}]{text}"
                for index, text in enumerate(recovery_lines)
            ) + "\n",
            encoding="utf-8",
        )
        selected_entries = parse_lyric_document(
            safe_read_text(recovery_lrc)
        )["entries"]
        assert timing_pattern_is_suspicious(selected_entries)
        recovered_entries, recovered_path = recover_matching_backup_timing(
            recovery_lrc,
            selected_entries,
        )
        assert recovered_path == recovery_backup
        assert not timing_pattern_is_suspicious(recovered_entries)
        assert [item["text"] for item in recovered_entries] == recovery_lines

        cancelled = threading.Event()
        cancelled.set()

        try:
            build_asr_cache_key(
                audio,
                language="auto",
                cancel_event=cancelled,
            )
        except AnalysisCancelled as exc:
            assert str(exc) == "Analysis cancelled."
        else:
            raise AssertionError(
                "Cache hashing ignored cancellation."
            )

        output.write_text(
            "old\n",
            encoding="utf-8",
        )
        output.chmod(0o640)

        # No destination: save exactly one LRC and create no backup.
        output.unlink()
        first_output, first_backup = safe_write_lrc(
            audio,
            "first",
        )
        assert first_output == output
        assert first_backup is None
        assert not list(
            Path(directory).glob(
                "song.lrc.bak-*"
            )
        )

        # Existing destination: preserve it once, then replace it.
        second_output, second_backup = safe_write_lrc(
            audio,
            "second",
        )

        backups = list(
            Path(directory).glob(
                "song.lrc.bak-*"
            )
        )

        assert second_output == output
        assert second_backup in backups
        assert len(backups) == 1
        assert output.read_text(
            encoding="utf-8"
        ) == "second\n"
        assert stat.S_IMODE(
            output.stat().st_mode
        ) == 0o600
        assert second_backup.read_text(
            encoding="utf-8"
        ) == "first\n"

        # Existing non-default permissions are preserved on both backup and
        # replacement.
        mode_audio = Path(directory) / "mode.flac"
        mode_audio.write_bytes(b"self-test")
        mode_output = Path(directory) / "mode.lrc"
        mode_output.write_text(
            "original\n",
            encoding="utf-8",
        )
        mode_output.chmod(0o640)
        mode_saved, mode_backup = safe_write_lrc(
            mode_audio,
            "replacement",
        )
        assert mode_backup is not None
        assert stat.S_IMODE(
            mode_saved.stat().st_mode
        ) == 0o640
        assert stat.S_IMODE(
            mode_backup.stat().st_mode
        ) == 0o640

        # Saving over an unexpectedly huge sidecar must fail before backup IO.
        huge_audio = Path(directory) / "huge.flac"
        huge_audio.write_bytes(b"audio")
        huge_output = Path(directory) / "huge.lrc"
        with huge_output.open("wb") as handle:
            handle.truncate(MAX_LYRICS_BYTES + 1)
        try:
            safe_write_lrc(huge_audio, "replacement")
        except VerseLatchError:
            pass
        else:
            raise AssertionError(
                "safe_write_lrc accepted an oversized existing target."
            )
        assert not list(Path(directory).glob("huge.lrc.bak-*"))

        # FIFO diagnostics must fail closed instead of blocking on open().
        if hasattr(os, "mkfifo"):
            fifo = Path(directory) / "diagnostic-fifo"
            os.mkfifo(fifo)
            assert tail_text_file(fifo) == ""

        victim = Path(directory) / "victim.txt"
        victim.write_text(
            "do-not-touch\n",
            encoding="utf-8",
        )

        linked_audio = Path(directory) / "linked.flac"
        linked_audio.write_bytes(b"self-test")
        linked_output = Path(directory) / "linked.lrc"
        linked_output.symlink_to(victim)

        try:
            safe_write_lrc(
                linked_audio,
                "replacement",
            )
        except VerseLatchError:
            pass
        else:
            raise AssertionError(
                "safe_write_lrc accepted a symlink target"
            )

        assert victim.read_text(
            encoding="utf-8"
        ) == "do-not-touch\n"

        with tempfile.TemporaryFile(
            mode="w+b"
        ) as diagnostic:
            diagnostic.write(
                b"A" * 32768
                + b"TAIL"
            )
            assert tail_binary_file(
                diagnostic,
                maximum_bytes=8,
            ).endswith("TAIL")

    assert hasattr(
        Gtk,
        "FileDialog",
    )

    assert hasattr(
        Adw,
        "ToolbarView",
    )

    assert hasattr(
        Adw,
        "HeaderBar",
    )

    assert hasattr(
        Adw,
        "WindowTitle",
    )

    assert hasattr(
        Adw,
        "AboutDialog",
    )

    assert hasattr(
        Gtk.License,
        "GPL_3_0_ONLY",
    )
    assert DEFAULT_THEME == "system"
    assert THEME_IDS == frozenset({"system", "light", "dark"})

    injected = {
        key: "unsafe"
        for key in UNSAFE_NATIVE_ENV_KEYS
    }
    original_values = {
        key: os.environ.get(key)
        for key in UNSAFE_NATIVE_ENV_KEYS
    }
    try:
        os.environ.update(injected)
        sanitized = native_tool_env(
            system_path=SYSTEM_EXEC_PATH,
            extra={"VERSE_LATCH_TEST": "1"},
        )
        assert sanitized["PATH"] == SYSTEM_EXEC_PATH
        assert sanitized["VERSE_LATCH_TEST"] == "1"
        assert not any(key in sanitized for key in UNSAFE_NATIVE_ENV_KEYS)
    finally:
        for key, value in original_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    css = css_for()
    css_provider = Gtk.CssProvider()
    css_errors: list[str] = []

    def record_css_error(_provider, section, error) -> None:
        css_errors.append(f"{section}: {error.message}")

    css_provider.connect("parsing-error", record_css_error)
    css_provider.load_from_string(css)

    assert ("CMU" + " Serif") not in css
    assert ("Latin Modern" + " Roman") not in css
    assert "background-color" not in css
    assert "--accent-bg-color" not in css
    assert re.search(r"#[0-9A-Fa-f]{6}", css) is None

    assert not css_errors, (
        "Application CSS errors: "
        + " | ".join(css_errors)
    )

    print(
        "VerseLatch self-test: OK"
    )


def main():
    if "--diagnostics" in sys.argv:
        print_diagnostics()
        return 0

    if "--version" in sys.argv:
        print(
            f"{APP_NAME} {APP_VERSION}"
        )
        return 0

    if "--self-test" in sys.argv:
        self_test()
        return 0

    smoke_test = (
        "--smoke-test"
        in sys.argv
    )

    arguments = [
        argument
        for argument in sys.argv
        if argument != "--smoke-test"
    ]

    LOGGER.info(
        "application start version=%s pid=%d python=%s gtk=%d.%d adw=%d.%d",
        APP_VERSION,
        os.getpid(),
        sys.version.split()[0],
        Gtk.get_major_version(),
        Gtk.get_minor_version(),
        Adw.get_major_version(),
        Adw.get_minor_version(),
    )

    application = VerseLatchApplication(
        smoke_test=smoke_test
    )

    def handle_sigterm() -> bool:
        LOGGER.info("SIGTERM received; shutting down analysis workers")
        if application.window is not None:
            application.window.shutdown_runtime()
        application.quit()
        return GLib.SOURCE_REMOVE

    if GLibUnix is not None and hasattr(GLibUnix, "signal_add"):
        try:
            GLibUnix.signal_add(
                GLib.PRIORITY_DEFAULT,
                signal.SIGTERM,
                handle_sigterm,
            )
        except TypeError:
            GLibUnix.signal_add(
                signal.SIGTERM,
                handle_sigterm,
            )
    else:
        signal.signal(
            signal.SIGTERM,
            lambda _signum, _frame: GLib.idle_add(handle_sigterm),
        )

    try:
        status = application.run(
            arguments
        )
    except KeyboardInterrupt:
        LOGGER.info("keyboard interrupt")
        if application.window is not None:
            application.window.shutdown_runtime()
        return 130
    except BaseException:
        LOGGER.exception("fatal uncaught exception escaped application.run")
        raise

    if (
        smoke_test
        and application.smoke_test_errors
    ):
        for error in (
            application.smoke_test_errors
        ):
            print(
                "VerseLatch CSS error: "
                + error,
                file=sys.stderr,
            )

        return 1

    LOGGER.info(
        "application run returned status=%s",
        status,
    )
    return status


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
