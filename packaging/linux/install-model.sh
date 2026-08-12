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
    echo "ERROR: do not run the VerseLatch model installer as root or through sudo." >&2
    exit 1
fi

MODE="${1-}"
if [[ -n "${MODE}" && "${MODE}" != "--verify-only" ]]; then
    echo "Usage: verselatch-model-install [--verify-only]" >&2
    exit 2
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

for required in sha256sum stat mktemp df awk cp mv chmod; do
    command -v "${required}" >/dev/null 2>&1 || {
        echo "ERROR: required command is missing: ${required}" >&2
        exit 1
    }
done

DATA_HOME="$(xdg_absolute_or_default XDG_DATA_HOME "${HOME}/.local/share")"
MODEL_DIR="${DATA_HOME}/verselatch/models"
MODEL="${MODEL_DIR}/ggml-large-v3-turbo.bin"
LEGACY_MODEL="${DATA_HOME}/lyricfix/models/ggml-large-v3-turbo.bin"
MODEL_SHA256="1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"
MODEL_SIZE="1624555275"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/98aa99a0a9db05ae2342309f5096248665f7cba3/ggml-large-v3-turbo.bin"
STAGE=""

cleanup() {
    local status=$?
    trap - EXIT
    [[ -z "${STAGE}" || ! -e "${STAGE}" ]] || rm -f -- "${STAGE}"
    exit "${status}"
}
trap cleanup EXIT

valid_model() {
    local path="$1"
    [[ -f "${path}" && ! -L "${path}" ]] \
        && [[ "$(stat -c %s -- "${path}" 2>/dev/null || true)" == "${MODEL_SIZE}" ]] \
        && printf '%s  %s\n' "${MODEL_SHA256}" "${path}" | sha256sum -c - >/dev/null 2>&1
}

for directory in "${DATA_HOME}/verselatch" "${MODEL_DIR}"; do
    if [[ -L "${directory}" || ( -e "${directory}" && ! -d "${directory}" ) ]]; then
        echo "ERROR: unsafe VerseLatch data directory: ${directory}" >&2
        exit 1
    fi
    mkdir -p -- "${directory}"
    [[ -d "${directory}" && ! -L "${directory}" ]] || {
        echo "ERROR: could not create VerseLatch data directory safely: ${directory}" >&2
        exit 1
    }
done

if [[ -L "${MODEL}" || ( -e "${MODEL}" && ! -f "${MODEL}" ) ]]; then
    echo "ERROR: model path is unsafe: ${MODEL}" >&2
    exit 1
fi

if valid_model "${MODEL}"; then
    echo "VerseLatch model integrity: OK"
    exit 0
fi

if [[ "${MODE}" == "--verify-only" ]]; then
    echo "ERROR: the VerseLatch ASR model is missing or failed verification." >&2
    exit 1
fi

# A verified legacy LyricFix model may be copied locally during the pre-publication
# rename. It is never linked, moved, or deleted, so the old installation remains
# independent and can be tested or removed separately.
if valid_model "${LEGACY_MODEL}"; then
    available_kib="$(df -Pk -- "${MODEL_DIR}" | awk 'NR==2 {print $4}')"
    if [[ ! "${available_kib}" =~ ^[0-9]+$ ]] || (( available_kib < 1900000 )); then
        echo "ERROR: at least ~1.9 GiB free space is required to copy the verified legacy model." >&2
        exit 1
    fi
    STAGE="$(mktemp --tmpdir="${MODEL_DIR}" '.ggml-large-v3-turbo.bin.XXXXXX')"
    echo "Reusing the verified local LyricFix model without network access..."
    cp --reflink=auto --preserve=mode,timestamps -- "${LEGACY_MODEL}" "${STAGE}"
    if ! valid_model "${STAGE}"; then
        echo "ERROR: locally copied model failed verification." >&2
        exit 1
    fi
    chmod 0644 -- "${STAGE}"
    mv -Tf -- "${STAGE}" "${MODEL}"
    STAGE=""
    echo "VerseLatch model installed from verified local legacy data: OK"
    exit 0
fi

command -v curl >/dev/null 2>&1 || {
    echo "ERROR: curl is required only when no verified local model is available." >&2
    exit 1
}

available_kib="$(df -Pk -- "${MODEL_DIR}" | awk 'NR==2 {print $4}')"
if [[ ! "${available_kib}" =~ ^[0-9]+$ ]] || (( available_kib < 2300000 )); then
    echo "ERROR: at least ~2.3 GiB free space is required to install the local ASR model." >&2
    exit 1
fi

STAGE="$(mktemp --tmpdir="${MODEL_DIR}" '.ggml-large-v3-turbo.bin.XXXXXX')"
echo "The model download is ~1.51 GiB and can take a while on slower connections."
echo "Progress is shown below; an existing verified model is reused instead of downloaded again."
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
    --output "${STAGE}" \
    -- "${MODEL_URL}"
then
    echo "ERROR: model download failed." >&2
    exit 1
fi

echo "Download complete. Verifying model integrity..."

if ! valid_model "${STAGE}"; then
    echo "ERROR: downloaded model failed the pinned size/SHA-256 identity check." >&2
    exit 1
fi
chmod 0644 -- "${STAGE}"
mv -Tf -- "${STAGE}" "${MODEL}"
STAGE=""
echo "VerseLatch model installation and SHA-256 verification: OK"
