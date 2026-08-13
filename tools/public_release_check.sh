#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail
IFS=$'\n\t'
export PYTHONDONTWRITEBYTECODE=1

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "${ROOT}"

HOMEPAGE="https://github.com/erhansavas/verselatch"
BUGTRACKER="https://github.com/erhansavas/verselatch/issues"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'MISSING REQUIRED RELEASE TOOL: %s\n' "$1" >&2
        exit 1
    }
}

printf '%s\n' '[1/3] Public-candidate tree and metadata policy'
python3 tools/verify_tree.py
tools/validate_appstream.sh --public

printf '%s\n' '[2/3] Canonical public endpoints'
need curl
for url in "${HOMEPAGE}" "${BUGTRACKER}"; do
    curl \
        --proto '=https' \
        --proto-redir '=https' \
        --fail \
        --silent \
        --show-error \
        --location \
        --max-time 20 \
        --user-agent 'VerseLatch-release-check/1.0.1' \
        --output /dev/null \
        -- "${url}"
    printf 'Reachable: %s\n' "${url}"
done

printf '%s\n' '[3/3] Publication prerequisite'
printf '%s\n' 'PUBLIC RELEASE CHECK: PASS'
printf '%s\n' 'Run the exact frozen candidate through the complete native and manual acceptance gates before tagging v1.0.1.'
