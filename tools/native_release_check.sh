#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail
IFS=$'\n\t'
export PYTHONDONTWRITEBYTECODE=1
export RUFF_NO_CACHE=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "${ROOT}"

public_metadata=1
case "${1-}" in
    "") ;;
    --public-metadata) public_metadata=1 ;;
    *)
        printf 'Usage: %s [--public-metadata]\n' "$0" >&2
        exit 2
        ;;
esac

assert_no_transient_artifacts() {
    local transient
    transient="$(find . \
        \( -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \
            -o -name '.mypy_cache' -o -name '*.egg-info' -o -name '.venv' -o -name 'build' \) \
        -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
        -print -quit)"
    if [[ -n "${transient}" ]]; then
        printf 'Transient quality/runtime artifact exists in release tree: %s\n' "${transient}" >&2
        exit 1
    fi
}

printf '%s\n' '[1/4] Complete source/package/native quality gate'
if (( public_metadata == 1 )); then
    ./tools/quality_gate.sh --public-metadata
else
    ./tools/quality_gate.sh
fi

printf '%s\n' '[2/4] Built-in GTK/regression tests'
python3 -E -s -B src/verselatch.py --self-test
G_DEBUG=fatal-criticals timeout --signal=TERM --kill-after=2s 12s \
    python3 -E -s -B src/verselatch.py --smoke-test
assert_no_transient_artifacts

printf '%s\n' '[3/4] Model integrity when present'
model="${XDG_DATA_HOME:-$HOME/.local/share}/verselatch/models/ggml-large-v3-turbo.bin"
if [[ -f "${model}" && ! -L "${model}" ]]; then
    actual_size="$(stat -c '%s' -- "${model}")"
    actual_sha="$(sha256sum -- "${model}" | awk '{print $1}')"
    [[ "${actual_size}" == '1624555275' ]]
    [[ "${actual_sha}" == '1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69' ]]
    printf '%s\n' 'Verified local Large v3 Turbo model: PASS'
else
    printf '%s\n' 'Verified local model not present; fresh model-install/download remains a separate manual gate.'
fi

printf '%s\n' '[4/4] Personal installer integration and GNOME/GIO registration'
./packaging/linux/install-user.sh

printf '%s\n' 'NATIVE RELEASE CHECK: PASS'
printf '%s\n' 'Manual acceptance remains: real audio Generate Draft, existing-LRC Verify & Align, cancel/restart, save/re-save, Turkish/non-ASCII content, 200% text scaling, keyboard-only, high contrast, and Orca.'
