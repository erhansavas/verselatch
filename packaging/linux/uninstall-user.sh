#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH="/usr/bin:/bin"
export PATH

if [[ -z "${HOME-}" || "${HOME}" != /* ]]; then
    echo "ERROR: HOME must be an absolute path." >&2
    exit 1
fi

if (( EUID == 0 )); then
    echo "ERROR: do not run the VerseLatch uninstaller as root or through sudo." >&2
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
CACHE_HOME="$(xdg_absolute_or_default XDG_CACHE_HOME "${HOME}/.cache")"
STATE_HOME="$(xdg_absolute_or_default XDG_STATE_HOME "${HOME}/.local/state")"
CONFIG_HOME="$(xdg_absolute_or_default XDG_CONFIG_HOME "${HOME}/.config")"

APP_ROOT="${DATA_HOME}/verselatch"
TARGET_DIR="${APP_ROOT}/app"
APP="${TARGET_DIR}/verselatch.py"
LAUNCHER="${HOME}/.local/bin/verselatch"
UNINSTALLER="${HOME}/.local/bin/verselatch-uninstall"
DESKTOP="${DATA_HOME}/applications/io.github.erhansavas.verselatch.desktop"
ICON="${DATA_HOME}/icons/hicolor/scalable/apps/io.github.erhansavas.verselatch.svg"
SYMBOLIC_ICON="${DATA_HOME}/icons/hicolor/symbolic/apps/io.github.erhansavas.verselatch-symbolic.svg"
METAINFO="${DATA_HOME}/metainfo/io.github.erhansavas.verselatch.metainfo.xml"
OWNERSHIP_LIB="${APP_ROOT}/install-ownership.sh"
INSTALL_MANIFEST="${APP_ROOT}/install-manifest.tsv"
MODEL_DIR="${DATA_HOME}/verselatch/models"
CACHE_DIR="${CACHE_HOME}/verselatch"
STATE_DIR="${STATE_HOME}/verselatch"
CONFIG_DIR="${CONFIG_HOME}/verselatch"

if [[ ! -d "${APP_ROOT}" || -L "${APP_ROOT}" ]]; then
    echo "ERROR: VerseLatch application root is missing or unsafe; refusing destructive uninstall: ${APP_ROOT}" >&2
    exit 1
fi

# The helper is executable policy input, so verify the exact 1.0.1 bytes before sourcing it.
OWNERSHIP_LIB_SHA256="604335566879a17e911a3e086eaa93f9a3dafbf141710a0536eb6f076c2066a3"
if [[ ! -f "${OWNERSHIP_LIB}" || -L "${OWNERSHIP_LIB}" ]] \
    || [[ "$(sha256sum -- "${OWNERSHIP_LIB}" | awk '{print $1}')" != "${OWNERSHIP_LIB_SHA256}" ]]; then
    echo "ERROR: VerseLatch ownership helper is missing or modified; refusing destructive uninstall." >&2
    exit 1
fi
# shellcheck source=packaging/linux/install-ownership.sh
source "${OWNERSHIP_LIB}"
if ! verselatch_validate_manifest "${INSTALL_MANIFEST}" '1.0.1'; then
    echo "ERROR: installed files do not match the VerseLatch ownership manifest; nothing was removed." >&2
    exit 1
fi

for proc in /proc/[0-9]*; do
    pid="${proc##*/}"
    argv=()
    mapfile -d '' -t argv < "${proc}/cmdline" 2>/dev/null || continue
    [[ "${#argv[@]}" -ge 2 ]] || continue
    executable="${argv[0]##*/}"

    case "${executable}" in
        python|python3|python3.*)
            for argument in "${argv[@]:1}"; do
                if [[ "${argument}" == "${APP}" ]]; then
                    echo "ERROR: VerseLatch is running (PID ${pid}). Close it and retry." >&2
                    exit 1
                fi
            done
            ;;
    esac
done

remove_owned_file() {
    local path="$1"
    local description="$2"

    if [[ -d "${path}" && ! -L "${path}" ]]; then
        echo "ERROR: ${description} path is unexpectedly a directory: ${path}" >&2
        exit 1
    fi

    if [[ -e "${path}" || -L "${path}" ]]; then
        rm -f -- "${path}"
        printf 'Removed: %s\n' "${path}"
    fi
}

# Manifest validation above proves the exact app-tree inventory and digests before
# recursive removal. Models and user data live outside this managed payload.
if [[ -e "${TARGET_DIR}" || -L "${TARGET_DIR}" ]]; then
    if [[ ! -d "${TARGET_DIR}" || -L "${TARGET_DIR}" ]]; then
        echo "ERROR: application payload path is unsafe: ${TARGET_DIR}" >&2
        exit 1
    fi
    rm -rf --one-file-system -- "${TARGET_DIR}"
    printf 'Removed: %s\n' "${TARGET_DIR}"
fi

remove_owned_file "${LAUNCHER}" "launcher"
remove_owned_file "${DESKTOP}" "desktop entry"
remove_owned_file "${ICON}" "application icon"
remove_owned_file "${SYMBOLIC_ICON}" "symbolic application icon"
remove_owned_file "${METAINFO}" "AppStream MetaInfo"
remove_owned_file "${OWNERSHIP_LIB}" "ownership helper"
remove_owned_file "${INSTALL_MANIFEST}" "ownership manifest"

rmdir -- "${APP_ROOT}" 2>/dev/null || true

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DATA_HOME}/applications" >/dev/null 2>&1 || true
fi

remove_owned_file "${UNINSTALLER}" "uninstaller"

printf '\nVerseLatch application files were uninstalled.\n'
printf 'Retained intentionally:\n'
printf '  Models: %s\n' "${MODEL_DIR}"
printf '  Cache:  %s\n' "${CACHE_DIR}"
printf '  Logs:   %s\n' "${STATE_DIR}"
printf '  Config: %s\n' "${CONFIG_DIR}"
printf '  LRC files next to your audio are never removed.\n'
printf '\nTo purge retained VerseLatch data later, inspect those paths first and remove only what you want.\n'
