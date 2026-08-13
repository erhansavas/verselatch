# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile

from .constants import MAX_LYRICS_BYTES
from .errors import VerseLatchError

def open_regular_readonly(
    path: Path,
    *,
    description: str,
    maximum_bytes: int | None = None,
) -> tuple[int, os.stat_result]:
    """Open one regular file without following the final symlink component."""
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK

    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerseLatchError(
            f"{description} could not be opened safely."
        ) from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise VerseLatchError(
                f"{description} must be a regular file."
            )
        if maximum_bytes is not None and metadata.st_size > maximum_bytes:
            raise VerseLatchError(
                f"{description} exceeds its safety size limit."
            )
        return descriptor, metadata
    except Exception:
        os.close(descriptor)
        raise

def regular_file_state(
    path: Path,
    *,
    description: str,
    maximum_bytes: int | None = None,
) -> tuple[int, int, int, int, int]:
    descriptor, metadata = open_regular_readonly(
        path,
        description=description,
        maximum_bytes=maximum_bytes,
    )
    os.close(descriptor)
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

def file_state_tuple(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

def require_regular_file_state(
    path: Path,
    expected_state: tuple[int, int, int, int, int],
    *,
    description: str,
    maximum_bytes: int | None = None,
) -> tuple[int, int, int, int, int]:
    """Require one regular file to still have the exact previously observed identity."""
    current_state = regular_file_state(
        path,
        description=description,
        maximum_bytes=maximum_bytes,
    )
    if current_state != expected_state:
        raise VerseLatchError(
            f"{description} changed after it was selected; result was discarded."
        )
    return current_state

def require_analysis_source_states(
    *,
    current_audio_path: Path | None,
    analyzed_audio_path: Path | None,
    analyzed_audio_state: tuple[int, int, int, int, int] | None,
    current_lyrics_path: Path | None,
    analyzed_lyrics_path: Path | None,
    analyzed_lyrics_state: tuple[int, int, int, int, int] | None,
    maximum_audio_bytes: int,
    maximum_lyrics_bytes: int,
) -> None:
    """Require Save inputs to be the exact sources used by the analysis result."""
    if analyzed_audio_path is None or analyzed_audio_state is None:
        raise VerseLatchError(
            "No validated analysis source is available. Run analysis again before saving."
        )
    if current_audio_path != analyzed_audio_path:
        raise VerseLatchError(
            "Audio selection changed after analysis. Run analysis again before saving."
        )
    try:
        require_regular_file_state(
            analyzed_audio_path,
            analyzed_audio_state,
            description="Audio source",
            maximum_bytes=maximum_audio_bytes,
        )
    except VerseLatchError as exc:
        raise VerseLatchError(
            "Audio changed or became unsafe after analysis. Run analysis again before saving."
        ) from exc

    if analyzed_lyrics_path is None:
        if analyzed_lyrics_state is not None:
            raise VerseLatchError(
                "Analysis source state is inconsistent. Run analysis again before saving."
            )
        if current_lyrics_path is not None:
            raise VerseLatchError(
                "Lyrics selection changed after analysis. Run analysis again before saving."
            )
        return

    if analyzed_lyrics_state is None:
        raise VerseLatchError(
            "No validated lyrics source is available. Run analysis again before saving."
        )
    if current_lyrics_path != analyzed_lyrics_path:
        raise VerseLatchError(
            "Lyrics selection changed after analysis. Run analysis again before saving."
        )
    try:
        require_regular_file_state(
            analyzed_lyrics_path,
            analyzed_lyrics_state,
            description="Lyrics source",
            maximum_bytes=maximum_lyrics_bytes,
        )
    except VerseLatchError as exc:
        raise VerseLatchError(
            "Lyrics changed or became unsafe after analysis. Run analysis again before saving."
        ) from exc

def safe_read_text(
    path: Path,
) -> str:
    if path.is_symlink():
        raise VerseLatchError(
            "Lyrics file must not be a symbolic link."
        )

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK

    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, NotADirectoryError):
        raise VerseLatchError(
            "Lyrics file does not exist."
        ) from None
    except OSError as exc:
        raise VerseLatchError(
            "Lyrics file could not be opened safely: " + str(exc)
        ) from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise VerseLatchError(
                "Lyrics source must be a regular file."
            )
        if metadata.st_size > MAX_LYRICS_BYTES:
            raise VerseLatchError(
                "Lyrics file exceeds the 4 MiB safety limit."
            )

        before_state = file_state_tuple(metadata)

        with os.fdopen(
            descriptor,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as handle:
            descriptor = -1
            text = handle.read()
            after = os.fstat(handle.fileno())

        after_state = file_state_tuple(after)
        if after_state != before_state:
            raise VerseLatchError(
                "Lyrics file changed while it was being read. Try again."
            )
        return text
    finally:
        if descriptor >= 0:
            os.close(descriptor)

def fsync_directory(
    path: Path,
) -> None:
    flags = os.O_RDONLY

    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    directory_fd = os.open(
        path,
        flags,
    )

    try:
        metadata = os.fstat(directory_fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise VerseLatchError(
                "Expected a regular directory for durable write."
            )
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

def safe_write_reviewed_lrc(
    *,
    content: str,
    current_audio_path: Path | None,
    analyzed_audio_path: Path | None,
    analyzed_audio_state: tuple[int, int, int, int, int] | None,
    current_lyrics_path: Path | None,
    analyzed_lyrics_path: Path | None,
    analyzed_lyrics_state: tuple[int, int, int, int, int] | None,
    maximum_audio_bytes: int,
    maximum_lyrics_bytes: int,
) -> tuple[Path, Path | None]:
    """Validate analyzed sources and immediately enter the atomic save path."""
    require_analysis_source_states(
        current_audio_path=current_audio_path,
        analyzed_audio_path=analyzed_audio_path,
        analyzed_audio_state=analyzed_audio_state,
        current_lyrics_path=current_lyrics_path,
        analyzed_lyrics_path=analyzed_lyrics_path,
        analyzed_lyrics_state=analyzed_lyrics_state,
        maximum_audio_bytes=maximum_audio_bytes,
        maximum_lyrics_bytes=maximum_lyrics_bytes,
    )
    if analyzed_audio_path is None:
        raise VerseLatchError(
            "No validated analysis source is available. Run analysis again before saving."
        )
    return safe_write_lrc(analyzed_audio_path, content)

def safe_write_lrc(
    audio_path: Path,
    content: str,
) -> tuple[Path, Path | None]:
    """Back up an existing regular LRC and atomically replace it."""
    encoded_content = (
        content.rstrip() + "\n"
    ).encode("utf-8")
    if len(encoded_content) > MAX_LYRICS_BYTES:
        raise VerseLatchError(
            "Generated lyrics exceed the 4 MiB safety limit."
        )

    output = audio_path.with_suffix(".lrc")
    parent = output.parent
    if not parent.is_dir() or parent.is_symlink():
        raise VerseLatchError(
            "The audio directory is not a usable regular directory."
        )

    output_mode: int | None = None
    original_state: tuple[int, int, int, int, int] | None = None
    created_backup: Path | None = None
    source_fd: int | None = None

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK

    try:
        source_fd = os.open(output, flags)
    except FileNotFoundError:
        source_fd = None
    except OSError as exc:
        raise VerseLatchError(
            "Refusing an unsafe or unreadable existing .lrc target."
        ) from exc

    if source_fd is not None:
        backup_path: Path | None = None
        backup_fd: int | None = None
        try:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise VerseLatchError(
                    "The target .lrc path is not a regular file."
                )
            if source_stat.st_size > MAX_LYRICS_BYTES:
                raise VerseLatchError(
                    "Existing .lrc exceeds the 4 MiB safety limit."
                )

            original_state = file_state_tuple(source_stat)
            # LRC is text; preserve ordinary rw bits but never propagate
            # executable or special permission bits to backups/replacements.
            output_mode = stat.S_IMODE(source_stat.st_mode) & 0o666

            backup_fd, backup_name = tempfile.mkstemp(
                prefix=output.name + ".bak-",
                dir=str(parent),
            )
            backup_path = Path(backup_name)
            os.fchmod(backup_fd, output_mode)

            with (
                os.fdopen(source_fd, "rb") as source_handle,
                os.fdopen(backup_fd, "wb") as backup_handle,
            ):
                source_fd = None
                backup_fd = None
                shutil.copyfileobj(
                    source_handle,
                    backup_handle,
                    length=1024 * 1024,
                )
                backup_handle.flush()
                os.fsync(backup_handle.fileno())

            fsync_directory(parent)
            created_backup = backup_path
        except Exception:
            if source_fd is not None:
                try:
                    os.close(source_fd)
                except OSError:
                    pass
            if backup_fd is not None:
                try:
                    os.close(backup_fd)
                except OSError:
                    pass
            if backup_path is not None:
                try:
                    backup_path.unlink()
                except FileNotFoundError:
                    pass
            raise

    fd, temporary = tempfile.mkstemp(
        prefix="." + output.name + ".",
        suffix=".tmp",
        dir=str(parent),
    )
    temporary_path = Path(temporary)

    try:
        if output_mode is not None:
            os.fchmod(fd, output_mode)

        with os.fdopen(
            fd,
            "wb",
        ) as handle:
            fd = -1
            handle.write(encoded_content)
            handle.flush()
            os.fsync(handle.fileno())

        # Detect common concurrent edits between backup and replacement.
        # This is a lost-update guard, not a cross-UID security boundary.
        current_state: tuple[int, int, int, int, int] | None
        try:
            check_fd, check_stat = open_regular_readonly(
                output,
                description="Existing .lrc target",
                maximum_bytes=MAX_LYRICS_BYTES,
            )
        except VerseLatchError:
            if output.exists() or output.is_symlink():
                raise
            current_state = None
        else:
            os.close(check_fd)
            current_state = file_state_tuple(check_stat)

        if current_state != original_state:
            raise VerseLatchError(
                "The target .lrc changed while saving; nothing was overwritten."
            )

        os.replace(temporary_path, output)
        fsync_directory(parent)
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return output, created_backup
