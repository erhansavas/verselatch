#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

mode="public"
case "${1-}" in
    "") ;;
    --private) mode="private" ;;
    --public) mode="public" ;;
    *)
        printf 'Usage: %s [--private|--public]\n' "$0" >&2
        exit 2
        ;;
esac

metadata="data/io.github.erhansavas.verselatch.metainfo.xml"
command -v appstreamcli >/dev/null 2>&1 || {
    printf 'MISSING REQUIRED TEST TOOL: appstreamcli\n' >&2
    exit 1
}

if [[ ! -f "${metadata}" || -L "${metadata}" ]]; then
    printf 'AppStream metadata is missing or unsafe: %s\n' "${metadata}" >&2
    exit 1
fi

if [[ "${mode}" == "private" ]]; then
    if grep -Fq '<url type="homepage">' "${metadata}"; then
        printf 'Private-RC metadata must not contain an unverified homepage URL.\n' >&2
        exit 1
    fi
    if ! grep -Fq '<release type="development" version="1.0.1"' "${metadata}"; then
        printf 'Private-RC metadata must carry an explicit development release.\n' >&2
        exit 1
    fi
else
    if ! grep -Eq '<url type="homepage">https://[^<]+</url>' "${metadata}"; then
        printf 'Public metadata requires a real HTTPS homepage before validation.\n' >&2
        exit 1
    fi
    if grep -Fq 'type="development"' "${metadata}"; then
        printf 'Public metadata must not retain the private development-release marker.\n' >&2
        exit 1
    fi
fi

set +e
validation_output="$(NO_COLOR=1 appstreamcli validate --pedantic "${metadata}" 2>&1)"
validation_status=$?
set -e
if (( validation_status == 0 )); then
    [[ -z "${validation_output}" ]] || printf '%s\n' "${validation_output}"
    printf 'AppStream %s policy: PASS\n' "${mode}"
    exit 0
fi

if [[ "${mode}" == "public" ]]; then
    printf '%s\n' "${validation_output}"
    printf 'AppStream public policy: FAIL\n' >&2
    exit "${validation_status}"
fi

# A private, deliberately unpublished build has no truthful homepage yet.
# appstreamcli reports that omission as one pedantic warning. Accept exactly
# that known warning and nothing else; all errors, pedantic notices, infos, or
# additional warnings remain fatal. This preserves strict validation without
# inventing a dead/public URL merely to turn the validator green.
mapfile -t diagnostic_lines < <(
    printf '%s\n' "${validation_output}" | LC_ALL=C grep -E '^[EWPI]: ' || true
)

if (( ${#diagnostic_lines[@]} != 1 )); then
    printf '%s\n' "${validation_output}"
    printf 'AppStream private policy: FAIL (expected exactly one deferred-homepage warning).\n' >&2
    exit 1
fi

if [[ "${diagnostic_lines[0]}" != W:* ]] \
    || [[ "${diagnostic_lines[0]}" != *'io.github.erhansavas.verselatch'* ]] \
    || [[ "${diagnostic_lines[0]}" != *': url-homepage-missing' ]]; then
    printf '%s\n' "${validation_output}"
    printf 'AppStream private policy: FAIL (unexpected validator diagnostic).\n' >&2
    exit 1
fi

printf '%s\n' 'AppStream validator: expected private-RC warning only (url-homepage-missing)'
printf 'AppStream private-RC policy: PASS (homepage intentionally deferred until a real public project URL exists)\n'
