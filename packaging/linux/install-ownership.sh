#!/usr/bin/bash
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
# Shared install/uninstall ownership checks. This file has no side effects when sourced.

verselatch_path_for_key() {
    case "$1" in
        launcher) printf '%s\n' "${LAUNCHER}" ;;
        uninstaller) printf '%s\n' "${UNINSTALLER}" ;;
        desktop) printf '%s\n' "${DESKTOP}" ;;
        icon) printf '%s\n' "${ICON}" ;;
        symbolic_icon) printf '%s\n' "${SYMBOLIC_ICON}" ;;
        metainfo) printf '%s\n' "${METAINFO}" ;;
        ownership_lib) printf '%s\n' "${OWNERSHIP_LIB}" ;;
        app/verselatch.py) printf '%s\n' "${TARGET_DIR}/verselatch.py" ;;
        app/verselatch_core/*.py)
            local name="${1#app/verselatch_core/}"
            [[ "${name}" != */* && "${name}" =~ ^[A-Za-z0-9_]+\.py$ ]] || return 1
            printf '%s\n' "${TARGET_DIR}/verselatch_core/${name}"
            ;;
        *) return 1 ;;
    esac
}

verselatch_sha256() {
    sha256sum -- "$1" | awk '{print $1}'
}

verselatch_require_regular_digest() {
    local path="$1" expected="$2" description="$3"
    if [[ ! -e "${path}" && ! -L "${path}" ]]; then
        return 1
    fi
    if [[ ! -f "${path}" || -L "${path}" ]]; then
        printf 'ERROR: %s is not a safe regular file: %s\n' "${description}" "${path}" >&2
        return 2
    fi
    if [[ "$(verselatch_sha256 "${path}")" != "${expected}" ]]; then
        printf 'ERROR: %s was modified or is not VerseLatch-owned: %s\n' "${description}" "${path}" >&2
        return 2
    fi
    return 0
}

verselatch_validate_manifest() {
    local manifest="$1" expected_version="$2"
    [[ -f "${manifest}" && ! -L "${manifest}" ]] || {
        printf 'ERROR: VerseLatch ownership manifest is missing or unsafe: %s\n' "${manifest}" >&2
        return 1
    }

    local line_no=0 version='' digest key path
    local -A seen=()
    local -a app_keys=()
    while IFS=$'\t' read -r digest key; do
        ((line_no += 1))
        if (( line_no == 1 )); then
            [[ "${digest}" == 'VerseLatch-Install-Manifest' && "${key}" == '1' ]] || {
                echo 'ERROR: VerseLatch ownership manifest header is invalid.' >&2; return 1; }
            continue
        fi
        if (( line_no == 2 )); then
            [[ "${digest}" == 'product_version' ]] || {
                echo 'ERROR: VerseLatch ownership manifest version record is invalid.' >&2; return 1; }
            version="${key}"
            [[ "${version}" == "${expected_version}" ]] || {
                printf 'ERROR: installed VerseLatch ownership manifest is for version %s, expected %s.\n' "${version}" "${expected_version}" >&2
                return 1
            }
            continue
        fi
        [[ "${digest}" =~ ^[0-9a-f]{64}$ && -n "${key}" ]] || {
            echo 'ERROR: VerseLatch ownership manifest contains an invalid record.' >&2; return 1; }
        [[ -z "${seen[${key}]+x}" ]] || {
            printf 'ERROR: duplicate ownership manifest key: %s\n' "${key}" >&2; return 1; }
        path="$(verselatch_path_for_key "${key}")" || {
            printf 'ERROR: unknown ownership manifest key: %s\n' "${key}" >&2; return 1; }
        seen["${key}"]="${digest}"
        [[ "${key}" != app/* ]] || app_keys+=("${key}")
        if [[ -e "${path}" || -L "${path}" ]]; then
            verselatch_require_regular_digest "${path}" "${digest}" "managed path" || return 1
        fi
    done < "${manifest}"

    for required_key in launcher uninstaller desktop icon symbolic_icon metainfo ownership_lib app/verselatch.py; do
        [[ -n "${seen[${required_key}]+x}" ]] || {
            printf 'ERROR: ownership manifest is missing required key: %s\n' "${required_key}" >&2; return 1; }
    done

    if [[ -e "${TARGET_DIR}" || -L "${TARGET_DIR}" ]]; then
        [[ -d "${TARGET_DIR}" && ! -L "${TARGET_DIR}" ]] || {
            printf 'ERROR: application payload path is unsafe: %s\n' "${TARGET_DIR}" >&2; return 1; }
        local entry_type actual_key inventory
        inventory="$(cd -- "${TARGET_DIR}" && find . -mindepth 1 -printf '%y\t%P\n' | LC_ALL=C sort)" || {
            printf 'ERROR: application payload inventory could not be read safely: %s\n' "${TARGET_DIR}" >&2
            return 1
        }
        while IFS=$'\t' read -r entry_type actual_key; do
            [[ -n "${entry_type}" ]] || continue
            case "${entry_type}:${actual_key}" in
                d:verselatch_core) continue ;;
                f:*)
                    [[ -n "${seen[app/${actual_key}]+x}" ]] || {
                        printf 'ERROR: unowned file exists inside VerseLatch application payload: %s\n' "${TARGET_DIR}/${actual_key}" >&2
                        return 1
                    }
                    ;;
                *)
                    printf 'ERROR: unowned or unsafe object exists inside VerseLatch application payload: %s\n' "${TARGET_DIR}/${actual_key}" >&2
                    return 1
                    ;;
            esac
        done <<< "${inventory}"
    fi
}

verselatch_validate_legacy_1_0_0() {
    local -A legacy_app=(
        [verselatch.py]=c96ee60d527f8e3100f786efc1d5ad763930d3d97669c57e49831b6e0740e411
        [verselatch_core/__init__.py]=5be6b96d9f5f98dfb609c64b321fba32b93f016145cb552425635dd16550c601
        [verselatch_core/alignment.py]=dde21769f2a6b45e74bea13d6abca91fa4ef69d941b55dbffcda1fdef3395169
        [verselatch_core/asr.py]=a841674a27049da678ab1bee4524175cf473539e21297b2f9521ad1b14693219
        [verselatch_core/constants.py]=e81d25c1b11d37d7a038f85ae9d8c18038c9ba3cecf84d16a2d6da115983cdb0
        [verselatch_core/errors.py]=8bdb1b592427a2bfac9a55f30653dbb3284f991b162d77aea2d2ae3e2c6897bb
        [verselatch_core/lrc.py]=60d84c57c38d2113788e11acf0d7820f825d204b4c347aa6b8e2a9befa87eb1a
        [verselatch_core/process.py]=a2c7afdf8ca36d31ef38bd6962aa88b470b642d640c7f4d2df05cba6d2e50ea0
        [verselatch_core/rhythm.py]=abb27e116edadca304ab36dd360149c54a74cd9524f630d6e2a3759208b0670b
        [verselatch_core/storage.py]=1d63d8ac1bb792d1f34b7a6f5709f2389d09501a12b574e6e6254a844b1f5183
    )
    [[ -d "${TARGET_DIR}" && ! -L "${TARGET_DIR}" ]] || return 1
    local rel entry_type inventory
    inventory="$(cd -- "${TARGET_DIR}" && find . -mindepth 1 -printf '%y\t%P\n' | LC_ALL=C sort)" || return 1
    while IFS=$'\t' read -r entry_type rel; do
        [[ -n "${entry_type}" ]] || continue
        case "${entry_type}:${rel}" in
            d:verselatch_core) continue ;;
            f:*) [[ -n "${legacy_app[${rel}]+x}" ]] || return 1 ;;
            *) return 1 ;;
        esac
    done <<< "${inventory}"
    for rel in "${!legacy_app[@]}"; do
        verselatch_require_regular_digest "${TARGET_DIR}/${rel}" "${legacy_app[${rel}]}" "VerseLatch 1.0.0 application file" || return 1
    done

    verselatch_require_regular_digest "${UNINSTALLER}" 60cbac64b44a898bca2cc50289a28b0fd5bbfd2c1d1c8bf807acbc76bb570002 'VerseLatch 1.0.0 uninstaller' || return 1
    verselatch_require_regular_digest "${ICON}" 09114fd1d62cbc92bacf07b199fa08012a110fed4af397fa947f1138df78345f 'VerseLatch 1.0.0 icon' || return 1
    verselatch_require_regular_digest "${SYMBOLIC_ICON}" c2ba7b66f1a5bc6d46fcd4968934c80d0706fed4c1b60b360f3974aa61cd0fe2 'VerseLatch 1.0.0 symbolic icon' || return 1
    verselatch_require_regular_digest "${METAINFO}" 76b166b1923bddfd6580360de9f7f4603e475c15fe569e969a1a28c181f27bb8 'VerseLatch 1.0.0 metainfo' || return 1
    [[ -f "${LAUNCHER}" && ! -L "${LAUNCHER}" && -f "${DESKTOP}" && ! -L "${DESKTOP}" ]] || return 1

    python3 -I - "${LAUNCHER}" "${APP}" "${DESKTOP}" <<'PY_LEGACY'
from pathlib import Path
import hashlib, re, shlex, sys
launcher, app, desktop = map(Path, sys.argv[1:4])
text = launcher.read_text(encoding='utf-8')
app_line = next((line for line in text.splitlines() if line.startswith('APP=')), None)
if app_line is None:
    raise SystemExit(1)
try:
    parsed = shlex.split(app_line[4:], posix=True)
except ValueError:
    raise SystemExit(1)
if parsed != [str(app)]:
    raise SystemExit(1)
normalized = re.sub(r'^APP=.*$', 'APP=__VERSELATCH_APP__', text, count=1, flags=re.M)
if hashlib.sha256(normalized.encode()).hexdigest() != 'ee119d1343dc667b6cc02b7d9513d6ed5373b0d04f0462c3d5f335fc5cd533bc':
    raise SystemExit(1)
expected_desktop = f'''[Desktop Entry]\nName=VerseLatch\nGenericName=Lyrics Timing Review Tool\nComment=Review and repair LRC timing locally\nTryExec={launcher}\nExec="{launcher}"\nIcon=io.github.erhansavas.verselatch\nTerminal=false\nType=Application\nCategories=AudioVideo;Audio;\nKeywords=lyrics;LRC;timing;audio;offline;alignment;\nStartupNotify=true\n'''
if desktop.read_text(encoding='utf-8') != expected_desktop:
    raise SystemExit(1)
PY_LEGACY
}

verselatch_any_managed_path_exists() {
    local path
    for path in "${TARGET_DIR}" "${LAUNCHER}" "${UNINSTALLER}" "${DESKTOP}" "${ICON}" "${SYMBOLIC_ICON}" "${METAINFO}" "${OWNERSHIP_LIB}" "${INSTALL_MANIFEST}"; do
        [[ -e "${path}" || -L "${path}" ]] && return 0
    done
    return 1
}

verselatch_preflight_install_ownership() {
    if [[ -e "${INSTALL_MANIFEST}" || -L "${INSTALL_MANIFEST}" ]]; then
        verselatch_validate_manifest "${INSTALL_MANIFEST}" '1.0.1' || return 1
        echo 'Existing VerseLatch 1.0.1 ownership manifest: OK'
        return 0
    fi
    if ! verselatch_any_managed_path_exists; then
        echo 'Installation ownership preflight: fresh install'
        return 0
    fi
    if verselatch_validate_legacy_1_0_0; then
        echo 'Installation ownership preflight: recognized exact VerseLatch 1.0.0 install'
        return 0
    fi
    echo 'ERROR: an existing VerseLatch path is not a recognized owned installation; refusing to overwrite it.' >&2
    echo 'Inspect the reported paths manually. VerseLatch will not guess ownership.' >&2
    return 1
}

verselatch_write_manifest() {
    local output="$1" version="$2" key path digest
    {
        printf 'VerseLatch-Install-Manifest\t1\n'
        printf 'product_version\t%s\n' "${version}"
        for key in launcher uninstaller desktop icon symbolic_icon metainfo ownership_lib; do
            path="$(verselatch_path_for_key "${key}")"
            [[ -f "${path}" && ! -L "${path}" ]] || return 1
            digest="$(verselatch_sha256 "${path}")"
            printf '%s\t%s\n' "${digest}" "${key}"
        done
        while IFS= read -r rel; do
            path="${TARGET_DIR}/${rel}"
            [[ -f "${path}" && ! -L "${path}" ]] || return 1
            digest="$(verselatch_sha256 "${path}")"
            printf '%s\tapp/%s\n' "${digest}" "${rel}"
        done < <(cd -- "${TARGET_DIR}" && find . -type f -printf '%P\n' | LC_ALL=C sort)
    } > "${output}"
}
