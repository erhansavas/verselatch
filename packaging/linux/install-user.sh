#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
USER_ORIGINAL_PATH="${PATH-}"
PATH="/usr/bin:/bin"
export PATH

if [[ -z "${HOME-}" || "${HOME}" != /* ]]; then
    echo "ERROR: HOME must be an absolute path." >&2
    exit 1
fi

# The desktop Exec field embeds the per-user launcher path. Reject the tiny set
# of path characters that would require Desktop Entry escaping rather than
# guessing at a transformed HOME value. Normal Arch home paths are unaffected.
readonly -a DESKTOP_EXEC_FORBIDDEN_CHARS=(
    $'\n'
    $'\r'
    '"'
    "\\"
    '`'
    '$'
    '%'
    '='
)
for forbidden_character in "${DESKTOP_EXEC_FORBIDDEN_CHARS[@]}"; do
    if [[ "${HOME}" == *"${forbidden_character}"* ]]; then
        printf '%s\n' 'ERROR: HOME contains a character unsupported by this installer.' >&2
        exit 1
    fi
done
unset forbidden_character

if (( EUID == 0 )); then
    echo "ERROR: do not run the VerseLatch installer as root or through sudo." >&2
    exit 1
fi

xdg_absolute_or_default() {
    local variable_name="$1"
    local fallback="$2"
    local value="${!variable_name-}"

    if [[ -n "${value}" && "${value}" == /* ]]; then
        printf '%s\n' "${value}"
    else
        printf '%s\n' "${fallback}"
    fi
}

DATA_HOME="$(xdg_absolute_or_default XDG_DATA_HOME "${HOME}/.local/share")"
STATE_HOME="$(xdg_absolute_or_default XDG_STATE_HOME "${HOME}/.local/state")"

APP_ROOT="${DATA_HOME}/verselatch"
TARGET_DIR="${APP_ROOT}/app"
APP="${TARGET_DIR}/verselatch.py"
LEGACY_APP="${HOME}/Projects/lyricfix/lyricfix.py"
LAUNCHER="${HOME}/.local/bin/verselatch"
UNINSTALLER="${HOME}/.local/bin/verselatch-uninstall"
DESKTOP="${DATA_HOME}/applications/io.github.erhansavas.verselatch.desktop"
ICON="${DATA_HOME}/icons/hicolor/scalable/apps/io.github.erhansavas.verselatch.svg"
SYMBOLIC_ICON="${DATA_HOME}/icons/hicolor/symbolic/apps/io.github.erhansavas.verselatch-symbolic.svg"
METAINFO="${DATA_HOME}/metainfo/io.github.erhansavas.verselatch.metainfo.xml"
ASR_MODEL="${DATA_HOME}/verselatch/models/ggml-large-v3-turbo.bin"
LEGACY_ASR_MODEL="${DATA_HOME}/lyricfix/models/ggml-large-v3-turbo.bin"
ASR_MODEL_SHA256="1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"
ASR_MODEL_SIZE="1624555275"
ASR_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/98aa99a0a9db05ae2342309f5096248665f7cba3/ggml-large-v3-turbo.bin"
EXPECTED_SHA256="c96ee60d527f8e3100f786efc1d5ad763930d3d97669c57e49831b6e0740e411"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
SOURCE="${PROJECT_ROOT}/src/verselatch.py"
CORE_SOURCE="${PROJECT_ROOT}/src/verselatch_core"
UNINSTALL_SOURCE="${SCRIPT_DIR}/uninstall-user.sh"
MODEL_INSTALL_SOURCE="${SCRIPT_DIR}/install-model.sh"
ICON_SOURCE="${PROJECT_ROOT}/data/io.github.erhansavas.verselatch.svg"
SYMBOLIC_ICON_SOURCE="${PROJECT_ROOT}/data/io.github.erhansavas.verselatch-symbolic.svg"
METAINFO_SOURCE="${PROJECT_ROOT}/data/io.github.erhansavas.verselatch.metainfo.xml"
LICENSE_FILE="${PROJECT_ROOT}/LICENSE"
MANIFEST_FILE="${PROJECT_ROOT}/SHA256SUMS"

APP_STAGE=""
APP_BACKUP=""
APP_HAD=0
APP_BACKUP_MOVED=0
APP_REPLACED=0

LAUNCHER_STAGE=""
LAUNCHER_BACKUP_DIR=""
LAUNCHER_HAD=0
LAUNCHER_REPLACED=0

UNINSTALLER_STAGE=""
UNINSTALLER_BACKUP_DIR=""
UNINSTALLER_HAD=0
UNINSTALLER_REPLACED=0

DESKTOP_STAGE=""
DESKTOP_BACKUP_DIR=""
DESKTOP_HAD=0
DESKTOP_REPLACED=0

ICON_STAGE=""
ICON_BACKUP_DIR=""
ICON_HAD=0
ICON_REPLACED=0

SYMBOLIC_ICON_STAGE=""
SYMBOLIC_ICON_BACKUP_DIR=""
SYMBOLIC_ICON_HAD=0
SYMBOLIC_ICON_REPLACED=0

METAINFO_STAGE=""
METAINFO_BACKUP_DIR=""
METAINFO_HAD=0
METAINFO_REPLACED=0

ASR_MODEL_STAGE=""
RHYTHM_SMOKE_DIR=""

cleanup() {
    local status=$?
    trap - EXIT

    [[ -z "${ASR_MODEL_STAGE}" || ! -e "${ASR_MODEL_STAGE}" ]] || rm -f -- "${ASR_MODEL_STAGE}"
    [[ -z "${RHYTHM_SMOKE_DIR}" || ! -d "${RHYTHM_SMOKE_DIR}" ]] || rm -rf -- "${RHYTHM_SMOKE_DIR}"
    [[ -z "${APP_STAGE}" || ! -e "${APP_STAGE}" ]] || rm -rf --one-file-system -- "${APP_STAGE}"
    [[ -z "${LAUNCHER_STAGE}" || ! -e "${LAUNCHER_STAGE}" ]] || rm -f -- "${LAUNCHER_STAGE}"
    [[ -z "${UNINSTALLER_STAGE}" || ! -e "${UNINSTALLER_STAGE}" ]] || rm -f -- "${UNINSTALLER_STAGE}"
    [[ -z "${DESKTOP_STAGE}" || ! -e "${DESKTOP_STAGE}" ]] || rm -f -- "${DESKTOP_STAGE}"
    [[ -z "${ICON_STAGE}" || ! -e "${ICON_STAGE}" ]] || rm -f -- "${ICON_STAGE}"
    [[ -z "${SYMBOLIC_ICON_STAGE}" || ! -e "${SYMBOLIC_ICON_STAGE}" ]] || rm -f -- "${SYMBOLIC_ICON_STAGE}"
    [[ -z "${METAINFO_STAGE}" || ! -e "${METAINFO_STAGE}" ]] || rm -f -- "${METAINFO_STAGE}"

    if (( status != 0 )); then
        if (( METAINFO_REPLACED == 1 )); then
            rm -f -- "${METAINFO}"
            if (( METAINFO_HAD == 1 )); then
                cp -a --no-dereference -- "${METAINFO_BACKUP_DIR}/original" "${METAINFO}"
            fi
        fi
        if (( SYMBOLIC_ICON_REPLACED == 1 )); then
            rm -f -- "${SYMBOLIC_ICON}"
            if (( SYMBOLIC_ICON_HAD == 1 )); then
                cp -a --no-dereference -- "${SYMBOLIC_ICON_BACKUP_DIR}/original" "${SYMBOLIC_ICON}"
            fi
        fi
        if (( ICON_REPLACED == 1 )); then
            rm -f -- "${ICON}"
            if (( ICON_HAD == 1 )); then
                cp -a --no-dereference -- "${ICON_BACKUP_DIR}/original" "${ICON}"
            fi
        fi
        if (( DESKTOP_REPLACED == 1 )); then
            rm -f -- "${DESKTOP}"
            if (( DESKTOP_HAD == 1 )); then
                cp -a --no-dereference -- "${DESKTOP_BACKUP_DIR}/original" "${DESKTOP}"
            fi
        fi

        if (( UNINSTALLER_REPLACED == 1 )); then
            rm -f -- "${UNINSTALLER}"
            if (( UNINSTALLER_HAD == 1 )); then
                cp -a --no-dereference -- "${UNINSTALLER_BACKUP_DIR}/original" "${UNINSTALLER}"
            fi
        fi

        if (( LAUNCHER_REPLACED == 1 )); then
            rm -f -- "${LAUNCHER}"
            if (( LAUNCHER_HAD == 1 )); then
                cp -a --no-dereference -- "${LAUNCHER_BACKUP_DIR}/original" "${LAUNCHER}"
            fi
        fi

        if (( APP_REPLACED == 1 )); then
            if [[ -d "${TARGET_DIR}" && ! -L "${TARGET_DIR}" ]]; then
                rm -rf --one-file-system -- "${TARGET_DIR}"
            fi
        fi

        if (( APP_BACKUP_MOVED == 1 )); then
            if (( APP_HAD == 1 )) && [[ -n "${APP_BACKUP}" && -d "${APP_BACKUP}" && ! -L "${APP_BACKUP}" ]]; then
                mv -T -- "${APP_BACKUP}" "${TARGET_DIR}"
                APP_BACKUP=""
                echo "Installation failed; previous VerseLatch application payload restored."
            fi
        elif (( APP_REPLACED == 1 && APP_HAD == 0 )); then
            echo "Installation failed; new VerseLatch application payload removed."
        fi
    fi

    [[ -z "${LAUNCHER_BACKUP_DIR}" || ! -d "${LAUNCHER_BACKUP_DIR}" ]] || rm -rf -- "${LAUNCHER_BACKUP_DIR}"
    [[ -z "${UNINSTALLER_BACKUP_DIR}" || ! -d "${UNINSTALLER_BACKUP_DIR}" ]] || rm -rf -- "${UNINSTALLER_BACKUP_DIR}"
    [[ -z "${DESKTOP_BACKUP_DIR}" || ! -d "${DESKTOP_BACKUP_DIR}" ]] || rm -rf -- "${DESKTOP_BACKUP_DIR}"
    [[ -z "${ICON_BACKUP_DIR}" || ! -d "${ICON_BACKUP_DIR}" ]] || rm -rf -- "${ICON_BACKUP_DIR}"
    [[ -z "${SYMBOLIC_ICON_BACKUP_DIR}" || ! -d "${SYMBOLIC_ICON_BACKUP_DIR}" ]] || rm -rf -- "${SYMBOLIC_ICON_BACKUP_DIR}"
    [[ -z "${METAINFO_BACKUP_DIR}" || ! -d "${METAINFO_BACKUP_DIR}" ]] || rm -rf -- "${METAINFO_BACKUP_DIR}"
    [[ -z "${APP_BACKUP}" || ! -d "${APP_BACKUP}" ]] || rm -rf --one-file-system -- "${APP_BACKUP}"

    exit "${status}"
}
trap cleanup EXIT

for required in python3 sha256sum mktemp timeout bash stat tee date grep awk head tail prlimit find sort; do
    if ! command -v "${required}" >/dev/null 2>&1; then
        echo "ERROR: required command is missing: ${required}"
        exit 1
    fi
done

required_files=(
    "${SOURCE}"
    "${UNINSTALL_SOURCE}"
    "${MODEL_INSTALL_SOURCE}"
    "${ICON_SOURCE}"
    "${SYMBOLIC_ICON_SOURCE}"
    "${METAINFO_SOURCE}"
    "${LICENSE_FILE}"
    "${MANIFEST_FILE}"
    "${CORE_SOURCE}/__init__.py"
    "${CORE_SOURCE}/constants.py"
    "${CORE_SOURCE}/errors.py"
    "${CORE_SOURCE}/lrc.py"
    "${CORE_SOURCE}/asr.py"
    "${CORE_SOURCE}/alignment.py"
    "${CORE_SOURCE}/process.py"
    "${CORE_SOURCE}/rhythm.py"
    "${CORE_SOURCE}/storage.py"
)
for required_file in "${required_files[@]}"; do
    if [[ ! -f "${required_file}" || -L "${required_file}" ]]; then
        echo "ERROR: package file is missing or unsafe: ${required_file}"
        exit 1
    fi
done
if [[ ! -d "${CORE_SOURCE}" || -L "${CORE_SOURCE}" ]]; then
    echo "ERROR: packaged core directory is missing or unsafe: ${CORE_SOURCE}"
    exit 1
fi


if ! (
    cd -- "${PROJECT_ROOT}"
    sha256sum --quiet --strict -c "$(basename -- "${MANIFEST_FILE}")"
); then
    echo "ERROR: package manifest integrity check failed." >&2
    exit 1
fi
echo "Package manifest integrity: OK"

manifest_inventory="$(awk '{print substr($0, 67)}' "${MANIFEST_FILE}" | LC_ALL=C sort)"
actual_inventory="$(
    cd -- "${PROJECT_ROOT}"
    find . -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort
)"
if [[ "${manifest_inventory}" != "${actual_inventory}" ]]; then
    echo "ERROR: package inventory differs from SHA256SUMS; refusing unlisted or missing files." >&2
    exit 1
fi
echo "Package inventory completeness: OK"

ACTUAL_SHA256="$(sha256sum -- "${SOURCE}" | awk '{print $1}')"
if [[ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]]; then
    echo "ERROR: package source integrity check failed."
    exit 1
fi
echo "Package source integrity: OK"

if ! bash -n "${UNINSTALL_SOURCE}" || ! bash -n "${MODEL_INSTALL_SOURCE}"; then
    echo "ERROR: packaged shell helper failed Bash syntax validation." >&2
    exit 1
fi
echo "Packaged shell helper syntax: OK"

for audio_tool in whisper-cli aubiotrack aubioonset; do
    if ! command -v "${audio_tool}" >/dev/null 2>&1; then
        echo "ERROR: required local audio tool is missing: ${audio_tool}"
        case "${audio_tool}" in
            whisper-cli)
                echo "Install the official Arch package once with: sudo pacman -S --needed whisper-cpp"
                ;;
            aubiotrack|aubioonset)
                echo "Install the official Arch package once with: sudo pacman -S --needed aubio"
                ;;
        esac
        exit 1
    fi
done

available_memory_kib="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || true)"
if [[ ! "${available_memory_kib}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: available memory could not be determined safely." >&2
    exit 1
fi
if (( available_memory_kib < 3276800 )); then
    echo "ERROR: VerseLatch 1.0.0 requires at least 3.2 GiB of currently available memory for its ASR model." >&2
    echo "Close heavy applications and run the installer again." >&2
    exit 1
fi
echo "Memory preflight: OK ($(( available_memory_kib / 1024 )) MiB available)"

python3 -I - <<'PY_PREFLIGHT'
import sys
try:
    import gi
except ModuleNotFoundError as exc:
    raise SystemExit(
        "PyGObject is missing. On Arch install once with: "
        "sudo pacman -S --needed python-gobject gtk4 libadwaita"
    ) from exc

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required.")

gtk = (Gtk.get_major_version(), Gtk.get_minor_version())
adw = (Adw.get_major_version(), Adw.get_minor_version())

if gtk < (4, 16):
    raise SystemExit(f"GTK 4.16+ required; found {gtk[0]}.{gtk[1]}")
if adw < (1, 8):
    raise SystemExit(f"libadwaita 1.8+ required; found {adw[0]}.{adw[1]}")

for required in ("FileDialog", "TextView", "DropDown"):
    if not hasattr(Gtk, required):
        raise SystemExit(f"Required GTK API missing: Gtk.{required}")

for required in (
    "ApplicationWindow",
    "AboutDialog",
    "ToolbarView",
    "HeaderBar",
    "Clamp",
    "PreferencesGroup",
    "ActionRow",
    "EntryRow",
    "ButtonRow",
    "ShortcutsDialog",
    "ShortcutsSection",
    "ShortcutsItem",
):
    if not hasattr(Adw, required):
        raise SystemExit(f"Required libadwaita API missing: Adw.{required}")

if not hasattr(Gtk.License, "GPL_3_0_ONLY"):
    raise SystemExit("Required GTK license metadata is missing: GPL_3_0_ONLY")
if not hasattr(Gtk.AccessibleProperty, "LABEL"):
    raise SystemExit("Required GTK accessibility metadata is missing: LABEL")

print(f"GTK/libadwaita preflight: OK ({gtk[0]}.{gtk[1]} / {adw[0]}.{adw[1]})")
PY_PREFLIGHT


MODEL_DIR="$(dirname -- "${ASR_MODEL}")"
if [[ -L "${MODEL_DIR}" || ( -e "${MODEL_DIR}" && ! -d "${MODEL_DIR}" ) ]]; then
    echo "ERROR: VerseLatch model directory is unsafe: ${MODEL_DIR}"
    exit 1
fi
mkdir -p -- "${MODEL_DIR}"
if [[ -L "${MODEL_DIR}" || ! -d "${MODEL_DIR}" ]]; then
    echo "ERROR: VerseLatch model directory could not be created safely: ${MODEL_DIR}"
    exit 1
fi

if [[ -L "${ASR_MODEL}" || ( -e "${ASR_MODEL}" && ! -f "${ASR_MODEL}" ) ]]; then
    echo "ERROR: Whisper Large v3 Turbo model path is unsafe: ${ASR_MODEL}"
    exit 1
fi

if [[ ! -f "${ASR_MODEL}" ]] \
    || [[ "$(stat -c %s -- "${ASR_MODEL}" 2>/dev/null || true)" != "${ASR_MODEL_SIZE}" ]] \
    || ! printf '%s  %s\n' "${ASR_MODEL_SHA256}" "${ASR_MODEL}" | sha256sum -c - >/dev/null 2>&1; then
    if [[ -f "${LEGACY_ASR_MODEL}" && ! -L "${LEGACY_ASR_MODEL}" ]] \
        && [[ "$(stat -c %s -- "${LEGACY_ASR_MODEL}" 2>/dev/null || true)" == "${ASR_MODEL_SIZE}" ]] \
        && printf '%s  %s\n' "${ASR_MODEL_SHA256}" "${LEGACY_ASR_MODEL}" | sha256sum -c - >/dev/null 2>&1; then
        available_kib="$(df -Pk -- "${MODEL_DIR}" | awk 'NR==2 {print $4}')"
        if [[ ! "${available_kib}" =~ ^[0-9]+$ ]] || (( available_kib < 1900000 )); then
            echo "ERROR: at least ~1.9 GiB free space is required to copy the verified legacy model." >&2
            exit 1
        fi
        ASR_MODEL_STAGE="$(mktemp --tmpdir="${MODEL_DIR}" '.ggml-large-v3-turbo.bin.XXXXXX')"
        echo "Reusing the verified local LyricFix model without network access..."
        cp --reflink=auto --preserve=mode,timestamps -- "${LEGACY_ASR_MODEL}" "${ASR_MODEL_STAGE}"
        if [[ "$(stat -c %s -- "${ASR_MODEL_STAGE}" 2>/dev/null || true)" != "${ASR_MODEL_SIZE}" ]] \
            || ! printf '%s  %s\n' "${ASR_MODEL_SHA256}" "${ASR_MODEL_STAGE}" | sha256sum -c - >/dev/null 2>&1; then
            echo "ERROR: locally copied legacy model failed verification." >&2
            exit 1
        fi
        chmod 0644 -- "${ASR_MODEL_STAGE}"
        mv -Tf -- "${ASR_MODEL_STAGE}" "${ASR_MODEL}"
        ASR_MODEL_STAGE=""
    else
        if ! command -v curl >/dev/null 2>&1; then
            echo "ERROR: curl is required only to download the missing ASR model." >&2
            echo "Install it once with: sudo pacman -S --needed curl" >&2
            exit 1
        fi

        ASR_MODEL_STAGE="$(mktemp --tmpdir="${MODEL_DIR}" '.ggml-large-v3-turbo.bin.XXXXXX')"

        # Full Large v3 Turbo is ~1.5 GiB. Leave room for atomic staging and margin.
        available_kib="$(df -Pk -- "${MODEL_DIR}" | awk 'NR==2 {print $4}')"
        if [[ ! "${available_kib}" =~ ^[0-9]+$ ]] || (( available_kib < 2300000 )); then
            echo "ERROR: at least ~2.3 GiB free space is required to install the local ASR model."
            exit 1
        fi

        echo "First-time setup requires the ~1.51 GiB Whisper Large v3 Turbo ASR model."
        echo "Download time depends on your connection; progress is shown below. Verified models are reused on later installs."
        echo "Press Ctrl+C to cancel safely; the temporary download is removed."
        if ! curl \
            --disable \
            --fail \
            --location \
            --progress-bar \
            --proto '=https' \
            --proto-redir '=https' \
            --max-redirs 10 \
            --remove-on-error \
            --show-error \
            --connect-timeout 20 \
            --max-time 3600 \
            --retry 3 \
            --retry-all-errors \
            --retry-delay 2 \
            --max-filesize 1700000000 \
            --output "${ASR_MODEL_STAGE}" \
            -- "${ASR_MODEL_URL}"
        then
            echo "ERROR: Whisper Large v3 Turbo model download failed. No VerseLatch application files were replaced." >&2
            exit 1
        fi

        echo "Download complete. Verifying model integrity..."

        if [[ "$(stat -c %s -- "${ASR_MODEL_STAGE}" 2>/dev/null || true)" != "${ASR_MODEL_SIZE}" ]]; then
            echo "ERROR: Whisper Large v3 Turbo model failed the published size check." >&2
            echo "No VerseLatch application files were replaced." >&2
            exit 1
        fi

        if ! printf '%s  %s\n' "${ASR_MODEL_SHA256}" "${ASR_MODEL_STAGE}" | sha256sum -c - >/dev/null 2>&1; then
            echo "ERROR: Whisper Large v3 Turbo model failed the published SHA-256 integrity check." >&2
            echo "No VerseLatch application files were replaced." >&2
            exit 1
        fi

        chmod 0644 -- "${ASR_MODEL_STAGE}"
        mv -Tf -- "${ASR_MODEL_STAGE}" "${ASR_MODEL}"
        ASR_MODEL_STAGE=""
    fi
fi
echo "Whisper Large v3 Turbo ASR model SHA-256 integrity: OK"

WHISPER_HELP="$(
    timeout --signal=TERM --kill-after=1s 10s whisper-cli -h 2>&1 \
        | head -c 1048576 \
        || true
)"
for required_flag in '--suppress-nst' '--output-json-full' '--max-len' '--split-on-word' '--language'; do
    if ! grep -Fq -- "${required_flag}" <<<"${WHISPER_HELP}"; then
        echo "ERROR: installed whisper-cli lacks required option: ${required_flag}"
        exit 1
    fi
done
echo "whisper-cli quality/word-segmentation preflight: OK"

# Exercise both rhythm binaries against a tiny synthetic WAV before touching
# the installed application. This verifies local decoding and process startup
# without using copyrighted material or network access.
RHYTHM_SMOKE_DIR="$(mktemp -d)"
python3 -I - "${RHYTHM_SMOKE_DIR}/tone.wav" <<'PY_RHYTHM_WAV'
import math
import struct
import sys
import wave

path = sys.argv[1]
rate = 16000
duration = 2.0
with wave.open(path, "wb") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(rate)
    frames = bytearray()
    for index in range(int(rate * duration)):
        phase = 2.0 * math.pi * 440.0 * index / rate
        envelope = 1.0 if (index % (rate // 2)) < 900 else 0.08
        sample = int(12000 * envelope * math.sin(phase))
        frames.extend(struct.pack("<h", sample))
    handle.writeframes(frames)
PY_RHYTHM_WAV

# Load the exact ASR model and exercise the same segmentation/JSON options
# used at runtime. The synthetic tone contains no copyrighted material.
timeout --signal=TERM --kill-after=5s 180s \
    prlimit --fsize=33554432 \
    whisper-cli \
    -m "${ASR_MODEL}" \
    -f "${RHYTHM_SMOKE_DIR}/tone.wav" \
    -t 1 -p 1 -l auto -ml 56 -sow -sns -ojf \
    -of "${RHYTHM_SMOKE_DIR}/whisper-smoke" -np \
    >/dev/null 2>"${RHYTHM_SMOKE_DIR}/whisper.err" || {
        tail -c 65536 -- "${RHYTHM_SMOKE_DIR}/whisper.err" >&2 || true
        echo "ERROR: whisper-cli quality-model smoke test failed."
        exit 1
    }
if [[ ! -f "${RHYTHM_SMOKE_DIR}/whisper-smoke.json" || -L "${RHYTHM_SMOKE_DIR}/whisper-smoke.json" ]]; then
    echo "ERROR: whisper-cli did not produce the expected full JSON output." >&2
    exit 1
fi
python3 -I - "${RHYTHM_SMOKE_DIR}/whisper-smoke.json" <<'PY_WHISPER_JSON'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(payload, dict) or "transcription" not in payload:
    raise SystemExit("whisper-cli full JSON smoke output is structurally invalid")
if not isinstance(payload["transcription"], list):
    raise SystemExit("whisper-cli transcription field is not a list")
PY_WHISPER_JSON
echo "whisper-cli quality-model/full-JSON smoke test: OK"

timeout --signal=TERM --kill-after=1s 10s \
    prlimit --fsize=2097152 \
    aubiotrack -i "${RHYTHM_SMOKE_DIR}/tone.wav" -T seconds \
    >/dev/null 2>"${RHYTHM_SMOKE_DIR}/track.err" || {
        tail -c 65536 -- "${RHYTHM_SMOKE_DIR}/track.err" >&2 || true
        echo "ERROR: aubiotrack local smoke test failed."
        exit 1
    }

timeout --signal=TERM --kill-after=1s 10s \
    prlimit --fsize=2097152 \
    aubioonset -i "${RHYTHM_SMOKE_DIR}/tone.wav" -T seconds \
    >/dev/null 2>"${RHYTHM_SMOKE_DIR}/onset.err" || {
        tail -c 65536 -- "${RHYTHM_SMOKE_DIR}/onset.err" >&2 || true
        echo "ERROR: aubioonset local smoke test failed."
        exit 1
    }
rm -rf -- "${RHYTHM_SMOKE_DIR}"
RHYTHM_SMOKE_DIR=""
echo "aubio rhythm preflight: OK"

STATE_DIR="${STATE_HOME}/verselatch"
if [[ -L "${APP_ROOT}" || ( -e "${APP_ROOT}" && ! -d "${APP_ROOT}" ) ]]; then
    echo "ERROR: VerseLatch application root is unsafe: ${APP_ROOT}"
    exit 1
fi
mkdir -p -- "${APP_ROOT}"
if [[ -L "${APP_ROOT}" || ! -d "${APP_ROOT}" ]]; then
    echo "ERROR: VerseLatch application root could not be created safely: ${APP_ROOT}"
    exit 1
fi
if [[ -e "${TARGET_DIR}" || -L "${TARGET_DIR}" ]]; then
    if [[ ! -d "${TARGET_DIR}" || -L "${TARGET_DIR}" ]]; then
        echo "ERROR: existing VerseLatch payload path is unsafe: ${TARGET_DIR}"
        exit 1
    fi
fi

mkdir -p -- \
    "$(dirname -- "${LAUNCHER}")" \
    "$(dirname -- "${DESKTOP}")" \
    "$(dirname -- "${ICON}")" \
    "$(dirname -- "${SYMBOLIC_ICON}")" \
    "$(dirname -- "${METAINFO}")"

if [[ -L "${STATE_DIR}" || ( -e "${STATE_DIR}" && ! -d "${STATE_DIR}" ) ]]; then
    echo "ERROR: VerseLatch state directory is unsafe: ${STATE_DIR}"
    exit 1
fi
mkdir -p -- "${STATE_DIR}"
if [[ -L "${STATE_DIR}" || ! -d "${STATE_DIR}" ]]; then
    echo "ERROR: VerseLatch state directory could not be created safely: ${STATE_DIR}"
    exit 1
fi
chmod 0700 -- "${STATE_DIR}"

# Build and validate the desktop entry before any installed file is replaced.
# Freedesktop requires a .desktop suffix; Audio is paired with its required
# AudioVideo main category and Utility is intentionally omitted to avoid a
# duplicate main-category menu entry.
DESKTOP_STAGE="$(mktemp --suffix=.desktop --tmpdir="$(dirname -- "${DESKTOP}")" '.verselatch-desktop.XXXXXX')"
cat > "${DESKTOP_STAGE}" <<DESKTOP_EOF
[Desktop Entry]
Name=VerseLatch
GenericName=Lyrics Timing Review Tool
Comment=Review and repair LRC timing locally
TryExec=${LAUNCHER}
Exec="${LAUNCHER}"
Icon=io.github.erhansavas.verselatch
Terminal=false
Type=Application
Categories=AudioVideo;Audio;
Keywords=lyrics;LRC;timing;audio;offline;alignment;
StartupNotify=true
DESKTOP_EOF
chmod 0644 -- "${DESKTOP_STAGE}"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "${DESKTOP_STAGE}"
fi

ICON_STAGE="$(mktemp --suffix=.svg --tmpdir="$(dirname -- "${ICON}")" '.verselatch-icon.XXXXXX')"
install -m 0644 -- "${ICON_SOURCE}" "${ICON_STAGE}"
python3 -I - "${ICON_STAGE}" <<'PY_ICON'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
path = Path(sys.argv[1])
root = ET.parse(path).getroot()
if not root.tag.endswith('svg') or root.attrib.get('viewBox') != '0 0 128 128':
    raise SystemExit('Packaged SVG icon failed structural validation.')
print('SVG icon structure: OK')
PY_ICON

SYMBOLIC_ICON_STAGE="$(mktemp --suffix=.svg --tmpdir="$(dirname -- "${SYMBOLIC_ICON}")" '.verselatch-symbolic-icon.XXXXXX')"
install -m 0644 -- "${SYMBOLIC_ICON_SOURCE}" "${SYMBOLIC_ICON_STAGE}"
python3 -I - "${SYMBOLIC_ICON_STAGE}" <<'PY_SYMBOLIC'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
path = Path(sys.argv[1])
root = ET.parse(path).getroot()
if not root.tag.endswith('svg') or 'viewBox' not in root.attrib:
    raise SystemExit('Packaged symbolic SVG failed structural validation.')
print('Symbolic SVG icon structure: OK')
PY_SYMBOLIC

METAINFO_STAGE="$(mktemp --suffix=.metainfo.xml --tmpdir="$(dirname -- "${METAINFO}")" '.verselatch-metainfo.XXXXXX')"
install -m 0644 -- "${METAINFO_SOURCE}" "${METAINFO_STAGE}"
python3 -I - "${METAINFO_STAGE}" <<'PY_METAINFO'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
path = Path(sys.argv[1])
root = ET.parse(path).getroot()
text = path.read_text(encoding='utf-8')
required = (
    '<id>io.github.erhansavas.verselatch</id>',
    '<metadata_license>MIT</metadata_license>',
    '<project_license>GPL-3.0-only</project_license>',
    '<developer id="io.github.erhansavas">',
    '<release version="1.0.0" date="2026-08-12">',
    '<url type="homepage">https://github.com/erhansavas/verselatch</url>',
    '<url type="bugtracker">https://github.com/erhansavas/verselatch/issues</url>',
)
if not root.tag.endswith('component') or any(token not in text for token in required):
    raise SystemExit('Packaged AppStream MetaInfo failed structural validation.')
if 'type="development"' in text:
    raise SystemExit('Packaged public AppStream metadata still contains a development release marker.')
print('AppStream MetaInfo public-release structure: OK')
PY_METAINFO

# Stop only the exact currently installed VerseLatch Python process.
running_pids=()
for proc in /proc/[0-9]*; do
    pid="${proc##*/}"
    [[ "${pid}" == "$$" ]] && continue

    argv=()
    mapfile -d '' -t argv < "${proc}/cmdline" 2>/dev/null || continue
    [[ "${#argv[@]}" -ge 2 ]] || continue

    executable="${argv[0]##*/}"
    case "${executable}" in
        python|python3|python3.*)
            for argument in "${argv[@]:1}"; do
                if [[ "${argument}" == "${APP}" || "${argument}" == "${LEGACY_APP}" ]]; then
                    running_pids+=("${pid}")
                    break
                fi
            done
            ;;
    esac
done

pid_is_verselatch() {
    local pid="$1"
    local proc="/proc/${pid}"
    local current_argv=()
    local executable

    [[ -r "${proc}/cmdline" ]] || return 1
    mapfile -d '' -t current_argv < "${proc}/cmdline" 2>/dev/null || return 1
    [[ "${#current_argv[@]}" -ge 2 ]] || return 1
    executable="${current_argv[0]##*/}"

    case "${executable}" in
        python|python3|python3.*)
            for argument in "${current_argv[@]:1}"; do
                if [[ "${argument}" == "${APP}" || "${argument}" == "${LEGACY_APP}" ]]; then
                    return 0
                fi
            done
            return 1
            ;;
        *)
            return 1
            ;;
    esac
}

for pid in "${running_pids[@]}"; do
    if pid_is_verselatch "${pid}"; then
        kill -TERM "${pid}" 2>/dev/null || true
    fi
done

for pid in "${running_pids[@]}"; do
    for _attempt in {1..100}; do
        if ! pid_is_verselatch "${pid}"; then
            break
        fi
        sleep 0.1
    done

    if pid_is_verselatch "${pid}"; then
        echo "ERROR: VerseLatch is still running. Close it and retry."
        exit 1
    fi
done

APP_STAGE="$(mktemp -d --tmpdir="${APP_ROOT}" '.app.install.XXXXXX')"
install -m 0755 -- "${SOURCE}" "${APP_STAGE}/verselatch.py"
mkdir -m 0755 -- "${APP_STAGE}/verselatch_core"
for core_file in "${CORE_SOURCE}"/*.py; do
    [[ -f "${core_file}" && ! -L "${core_file}" ]] || {
        echo "ERROR: unsafe core payload source: ${core_file}" >&2
        exit 1
    }
    install -m 0644 -- "${core_file}" "${APP_STAGE}/verselatch_core/$(basename -- "${core_file}")"
done

printf '%s\n' '[1/13] Python payload syntax'
python3 -I - "${APP_STAGE}" <<'PY_SYNTAX'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for path in sorted(root.rglob("*.py")):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
print("Python payload syntax: OK")
PY_SYNTAX

printf '%s\n' '[2/13] Static tree + built-in regression/security/design tests'
python3 -I "${PROJECT_ROOT}/tools/verify_tree.py"
python3 -E -s -B "${APP_STAGE}/verselatch.py" --self-test

printf '%s\n' '[3/13] Isolated staged payload / runtime policy'
if [[ "$(python3 -E -s -B "${APP_STAGE}/verselatch.py" --version)" != "VerseLatch 1.0.0" ]]; then
    echo "ERROR: staged modular payload/version check failed." >&2
    exit 1
fi
python3 -I "${PROJECT_ROOT}/tools/verify_tree.py" >/dev/null
printf '%s\n' 'Policy/design/lifecycle audit: OK'

printf '%s\n' '[4/13] GTK/libadwaita empty + populated UI smoke test'
G_DEBUG=fatal-criticals \
    timeout --signal=TERM --kill-after=2s 12s \
    python3 -E -s -B "${APP_STAGE}/verselatch.py" --smoke-test

printf '%s\n' '[5/13] Tested source consistency'
TESTED_SHA256="$(sha256sum -- "${APP_STAGE}/verselatch.py" | awk '{print $1}')"
if [[ "${TESTED_SHA256}" != "${EXPECTED_SHA256}" ]]; then
    echo "ERROR: staged source changed during tests."
    exit 1
fi

expected_stage_inventory="$(
    {
        printf '%s\n' 'verselatch.py'
        for core_file in "${CORE_SOURCE}"/*.py; do
            printf 'verselatch_core/%s\n' "$(basename -- "${core_file}")"
        done
    } | LC_ALL=C sort
)"
actual_stage_inventory="$(
    cd -- "${APP_STAGE}"
    find . -type f -printf '%P\n' | LC_ALL=C sort
)"
if [[ "${expected_stage_inventory}" != "${actual_stage_inventory}" ]]; then
    printf '%s\n' 'ERROR: staged application payload changed during tests.' >&2
    diff -u \
        <(printf '%s\n' "${expected_stage_inventory}") \
        <(printf '%s\n' "${actual_stage_inventory}") >&2 || true
    exit 1
fi
printf '%s\n' 'Staged application inventory: OK'

printf '%s\n' '[6/13] Atomic modular application payload replacement'
if [[ -d "${TARGET_DIR}" && ! -L "${TARGET_DIR}" ]]; then
    APP_HAD=1
    APP_BACKUP="$(mktemp -d --tmpdir="${APP_ROOT}" '.app.backup.XXXXXX')"
    rmdir -- "${APP_BACKUP}"
    mv -T -- "${TARGET_DIR}" "${APP_BACKUP}"
    APP_BACKUP_MOVED=1
fi
mv -T -- "${APP_STAGE}" "${TARGET_DIR}"
APP_STAGE=""
APP_REPLACED=1
chmod 0755 -- "${APP}"

INSTALLED_SHA256="$(sha256sum -- "${APP}" | awk '{print $1}')"
if [[ "${INSTALLED_SHA256}" != "${EXPECTED_SHA256}" ]]; then
    echo "ERROR: installed source consistency check failed."
    exit 1
fi
for core_file in "${CORE_SOURCE}"/*.py; do
    installed_core="${TARGET_DIR}/verselatch_core/$(basename -- "${core_file}")"
    if [[ ! -f "${installed_core}" || -L "${installed_core}" ]] || ! cmp -s -- "${core_file}" "${installed_core}"; then
        echo "ERROR: installed core payload consistency check failed: ${installed_core}" >&2
        exit 1
    fi
done

printf '%s\n' '[7/13] Deterministic launcher replacement'
if [[ -e "${LAUNCHER}" || -L "${LAUNCHER}" ]]; then
    if [[ -d "${LAUNCHER}" && ! -L "${LAUNCHER}" ]]; then
        echo "ERROR: launcher path is a directory: ${LAUNCHER}"
        exit 1
    fi

    LAUNCHER_HAD=1
    LAUNCHER_BACKUP_DIR="$(mktemp -d --tmpdir="$(dirname -- "${LAUNCHER}")" '.verselatch-launcher-backup.XXXXXX')"
    cp -a --no-dereference -- "${LAUNCHER}" "${LAUNCHER_BACKUP_DIR}/original"
fi

LAUNCHER_STAGE="$(mktemp --tmpdir="$(dirname -- "${LAUNCHER}")" '.verselatch-launcher.XXXXXX')"
# Embed the installed app path as a Bash-safe assignment. This matters when a
# valid absolute XDG data path contains spaces or shell metacharacters.
APP_SHELL_LITERAL="$(printf '%q' "${APP}")"
cat > "${LAUNCHER_STAGE}" <<LAUNCHER_EOF
#!/usr/bin/bash
set -euo pipefail
umask 077
PATH="/usr/bin:/bin"
export PATH

if [[ -z "\${HOME-}" || "\${HOME}" != /* ]]; then
    printf 'VerseLatch: HOME must be an absolute path.\n' >&2
    exit 1
fi

APP=${APP_SHELL_LITERAL}
if [[ -n "\${XDG_STATE_HOME-}" && "\${XDG_STATE_HOME}" == /* ]]; then
    STATE_HOME="\${XDG_STATE_HOME}"
else
    STATE_HOME="\${HOME}/.local/state"
fi
STATE_DIR="\${STATE_HOME}/verselatch"
STDERR_LOG="\${STATE_DIR}/stderr.log"
LAST_EXIT="\${STATE_DIR}/last-exit.txt"

if [[ -L "\${STATE_DIR}" || ( -e "\${STATE_DIR}" && ! -d "\${STATE_DIR}" ) ]]; then
    printf 'VerseLatch: unsafe state directory: %s\n' "\${STATE_DIR}" >&2
    exit 1
fi
mkdir -p -- "\${STATE_DIR}"
if [[ -L "\${STATE_DIR}" || ! -d "\${STATE_DIR}" ]]; then
    printf 'VerseLatch: could not create state directory safely: %s\n' "\${STATE_DIR}" >&2
    exit 1
fi
chmod 0700 -- "\${STATE_DIR}" 2>/dev/null || true

# Never append through symlinks or special files in the diagnostics directory.
for diagnostic in "\${STDERR_LOG}" "\${LAST_EXIT}"; do
    if [[ -L "\${diagnostic}" ]]; then
        rm -f -- "\${diagnostic}"
    elif [[ -e "\${diagnostic}" && ! -f "\${diagnostic}" ]]; then
        printf 'VerseLatch: unsafe diagnostics path: %s\n' "\${diagnostic}" >&2
        exit 1
    fi
done

# Keep GTK/native stderr persistent and bounded. The tee process exists only
# for this foreground VerseLatch run and cannot become a background service.
if [[ -f "\${STDERR_LOG}" ]]; then
    size="\$(stat -c %s -- "\${STDERR_LOG}" 2>/dev/null || printf '0')"
    if [[ "\${size}" =~ ^[0-9]+$ ]] && (( size > 524288 )); then
        rm -f -- "\${STDERR_LOG}.2"
        [[ ! -f "\${STDERR_LOG}.1" ]] || mv -Tf -- "\${STDERR_LOG}.1" "\${STDERR_LOG}.2"
        mv -Tf -- "\${STDERR_LOG}" "\${STDERR_LOG}.1"
    fi
fi

printf '%s pid=%s launch %q\n' "\$(date --iso-8601=seconds)" "\$$" "\${APP}" >> "\${STDERR_LOG}"
chmod 0600 -- "\${STDERR_LOG}" 2>/dev/null || true

set +e
python3 -E -s -B "\${APP}" "\$@" 2> >(tee -a "\${STDERR_LOG}" >&2)
status=\$?
set -e

printf '%s exit_code=%s\n' "\$(date --iso-8601=seconds)" "\${status}" > "\${LAST_EXIT}"
chmod 0600 -- "\${LAST_EXIT}" 2>/dev/null || true
printf '%s exit_code=%s\n' "\$(date --iso-8601=seconds)" "\${status}" >> "\${STDERR_LOG}"

if (( status != 0 && status != 130 )); then
    printf 'VerseLatch exited unexpectedly (code %s).\n' "\${status}" >&2
    printf 'Run: %s --diagnostics\n' "\$0" >&2
    printf 'Persistent logs: %s\n' "\${STATE_DIR}" >&2
fi

exit "\${status}"
LAUNCHER_EOF
chmod 0755 -- "${LAUNCHER_STAGE}"
bash -n "${LAUNCHER_STAGE}"
mv -Tf -- "${LAUNCHER_STAGE}" "${LAUNCHER}"
LAUNCHER_STAGE=""
LAUNCHER_REPLACED=1

if [[ "$("${LAUNCHER}" --version)" != "VerseLatch 1.0.0" ]]; then
    echo "ERROR: launcher/version check failed."
    exit 1
fi

if ! "${LAUNCHER}" --diagnostics | grep -Fq 'VerseLatch 1.0.0 diagnostics'; then
    echo "ERROR: persistent diagnostics check failed."
    exit 1
fi

printf '%s\n' '[8/13] Uninstaller replacement'
if [[ -e "${UNINSTALLER}" || -L "${UNINSTALLER}" ]]; then
    if [[ -d "${UNINSTALLER}" && ! -L "${UNINSTALLER}" ]]; then
        echo "ERROR: uninstaller path is a directory: ${UNINSTALLER}"
        exit 1
    fi

    UNINSTALLER_HAD=1
    UNINSTALLER_BACKUP_DIR="$(mktemp -d --tmpdir="$(dirname -- "${UNINSTALLER}")" '.verselatch-uninstaller-backup.XXXXXX')"
    cp -a --no-dereference -- "${UNINSTALLER}" "${UNINSTALLER_BACKUP_DIR}/original"
fi

UNINSTALLER_STAGE="$(mktemp --tmpdir="$(dirname -- "${UNINSTALLER}")" '.verselatch-uninstaller.XXXXXX')"
install -m 0755 -- "${UNINSTALL_SOURCE}" "${UNINSTALLER_STAGE}"
bash -n "${UNINSTALLER_STAGE}"
mv -Tf -- "${UNINSTALLER_STAGE}" "${UNINSTALLER}"
UNINSTALLER_STAGE=""
UNINSTALLER_REPLACED=1

printf '%s\n' '[9/13] Desktop entry replacement'
if [[ -e "${DESKTOP}" || -L "${DESKTOP}" ]]; then
    if [[ -d "${DESKTOP}" && ! -L "${DESKTOP}" ]]; then
        echo "ERROR: desktop entry path is a directory: ${DESKTOP}"
        exit 1
    fi

    DESKTOP_HAD=1
    DESKTOP_BACKUP_DIR="$(mktemp -d --tmpdir="$(dirname -- "${DESKTOP}")" '.verselatch-desktop-backup.XXXXXX')"
    cp -a --no-dereference -- "${DESKTOP}" "${DESKTOP_BACKUP_DIR}/original"
fi

if [[ -z "${DESKTOP_STAGE}" || ! -f "${DESKTOP_STAGE}" || -L "${DESKTOP_STAGE}" ]]; then
    echo "ERROR: validated desktop-entry stage is missing or unsafe."
    exit 1
fi

mv -Tf -- "${DESKTOP_STAGE}" "${DESKTOP}"
DESKTOP_STAGE=""
DESKTOP_REPLACED=1

printf '%s\n' '[10/13] Icon replacement'
if [[ -e "${ICON}" || -L "${ICON}" ]]; then
    if [[ -d "${ICON}" && ! -L "${ICON}" ]]; then
        echo "ERROR: icon path is a directory: ${ICON}" >&2
        exit 1
    fi
    ICON_HAD=1
    ICON_BACKUP_DIR="$(mktemp -d --tmpdir="$(dirname -- "${ICON}")" '.verselatch-icon-backup.XXXXXX')"
    cp -a --no-dereference -- "${ICON}" "${ICON_BACKUP_DIR}/original"
fi
if [[ -z "${ICON_STAGE}" || ! -f "${ICON_STAGE}" || -L "${ICON_STAGE}" ]]; then
    echo "ERROR: staged icon is missing or unsafe." >&2
    exit 1
fi
mv -Tf -- "${ICON_STAGE}" "${ICON}"
ICON_STAGE=""
ICON_REPLACED=1

printf '%s\n' '[11/13] Symbolic icon replacement'
if [[ -e "${SYMBOLIC_ICON}" || -L "${SYMBOLIC_ICON}" ]]; then
    if [[ -d "${SYMBOLIC_ICON}" && ! -L "${SYMBOLIC_ICON}" ]]; then
        echo "ERROR: symbolic icon path is a directory: ${SYMBOLIC_ICON}" >&2
        exit 1
    fi
    SYMBOLIC_ICON_HAD=1
    SYMBOLIC_ICON_BACKUP_DIR="$(mktemp -d --tmpdir="$(dirname -- "${SYMBOLIC_ICON}")" '.verselatch-symbolic-icon-backup.XXXXXX')"
    cp -a --no-dereference -- "${SYMBOLIC_ICON}" "${SYMBOLIC_ICON_BACKUP_DIR}/original"
fi
if [[ -z "${SYMBOLIC_ICON_STAGE}" || ! -f "${SYMBOLIC_ICON_STAGE}" || -L "${SYMBOLIC_ICON_STAGE}" ]]; then
    echo "ERROR: staged symbolic icon is missing or unsafe." >&2
    exit 1
fi
mv -Tf -- "${SYMBOLIC_ICON_STAGE}" "${SYMBOLIC_ICON}"
SYMBOLIC_ICON_STAGE=""
SYMBOLIC_ICON_REPLACED=1

printf '%s\n' '[12/13] AppStream MetaInfo replacement'
if [[ -e "${METAINFO}" || -L "${METAINFO}" ]]; then
    if [[ -d "${METAINFO}" && ! -L "${METAINFO}" ]]; then
        echo "ERROR: metainfo path is a directory: ${METAINFO}" >&2
        exit 1
    fi
    METAINFO_HAD=1
    METAINFO_BACKUP_DIR="$(mktemp -d --tmpdir="$(dirname -- "${METAINFO}")" '.verselatch-metainfo-backup.XXXXXX')"
    cp -a --no-dereference -- "${METAINFO}" "${METAINFO_BACKUP_DIR}/original"
fi
if [[ -z "${METAINFO_STAGE}" || ! -f "${METAINFO_STAGE}" || -L "${METAINFO_STAGE}" ]]; then
    echo "ERROR: staged metainfo is missing or unsafe." >&2
    exit 1
fi
mv -Tf -- "${METAINFO_STAGE}" "${METAINFO}"
METAINFO_STAGE=""
METAINFO_REPLACED=1

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$(dirname -- "${DESKTOP}")" >/dev/null 2>&1 || true
fi

printf '%s\n' '[13/13] Desktop/GIO application registration'
python3 -I -B - "${DESKTOP}" "${LAUNCHER}" <<'PY_DESKTOP_REGISTRATION'
from pathlib import Path
import os
import shlex
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

desktop_path = Path(sys.argv[1])
launcher_path = str(Path(sys.argv[2]))
desktop_id = "io.github.erhansavas.verselatch.desktop"

keyfile = GLib.KeyFile()
keyfile.load_from_file(str(desktop_path), GLib.KeyFileFlags.NONE)
try_exec = keyfile.get_string("Desktop Entry", "TryExec")
if try_exec != launcher_path:
    raise SystemExit(
        f"installed TryExec is not the executable path: {try_exec!r} != {launcher_path!r}"
    )
if not Path(launcher_path).is_file() or not os.access(launcher_path, os.X_OK):
    raise SystemExit(f"installed TryExec target is not an executable regular file: {launcher_path!r}")

exec_value = keyfile.get_string("Desktop Entry", "Exec")
expected_exec_value = f'"{launcher_path}"'
if exec_value != expected_exec_value:
    raise SystemExit(
        f"installed Exec command is not the expected quoted launcher: {exec_value!r} != {expected_exec_value!r}"
    )

apps = [info for info in Gio.AppInfo.get_all() if info.get_id() == desktop_id]
if len(apps) != 1:
    raise SystemExit(f"GIO did not register exactly one {desktop_id} entry (found {len(apps)})")
app = apps[0]
if not app.should_show():
    raise SystemExit(f"GIO registered {desktop_id} but marks it hidden from application menus")

# get_executable() is documented as a debugging/label value and GDesktopAppInfo
# may preserve the Exec token's quote characters there. Validate the command line
# that GIO says it will launch, then compare its parsed argv semantics instead.
commandline = app.get_commandline()
if not commandline:
    raise SystemExit(f"GIO registered {desktop_id} without a launch command line")
try:
    argv = shlex.split(commandline, posix=True)
except ValueError as exc:
    raise SystemExit(f"GIO launch command line is not parseable: {commandline!r}: {exc}") from exc
if argv != [launcher_path]:
    raise SystemExit(
        f"GIO launch command mismatch: argv={argv!r} expected={[launcher_path]!r}"
    )
print('Desktop/GIO application registration: OK')
PY_DESKTOP_REGISTRATION

# Commit the transaction. The previous app directory was only a rollback
# snapshot; remove it after all owned files have been replaced successfully.
APP_REPLACED=0
APP_BACKUP_MOVED=0
if [[ -n "${APP_BACKUP}" && -d "${APP_BACKUP}" && ! -L "${APP_BACKUP}" ]]; then
    rm -rf --one-file-system -- "${APP_BACKUP}"
fi
APP_BACKUP=""
LAUNCHER_REPLACED=0
UNINSTALLER_REPLACED=0
DESKTOP_REPLACED=0
ICON_REPLACED=0
SYMBOLIC_ICON_REPLACED=0
METAINFO_REPLACED=0

printf '\nVerseLatch 1.0.0 installed successfully.\n'
printf 'App:     %s\n' "${APP}"
printf 'Start:   %s\n' "${LAUNCHER}"
printf 'Remove:  %s\n' "${UNINSTALLER}"
printf 'Version: %s\n' "$("${LAUNCHER}" --version)"
printf 'Logs:    %s\n' "${STATE_DIR}"
if [[ "${LEGACY_APP}" != "${APP}" && -f "${LEGACY_APP}" && ! -L "${LEGACY_APP}" ]]; then
    printf 'Legacy:  %s (older installer payload; left untouched)\n' "${LEGACY_APP}"
fi

case ":${USER_ORIGINAL_PATH}:" in
    *":${HOME}/.local/bin:"*)
        ;;
    *)
        printf '\nNote: ~/.local/bin is not in this shell PATH. The desktop launcher was installed.\n'
        printf 'For terminal use, add this line to your shell startup file (Bash: ~/.bashrc), then open a new terminal:\n'
        printf '%s\n' "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac
