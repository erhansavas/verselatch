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

portable=0
public_metadata=1
for arg in "$@"; do
    case "${arg}" in
        --portable) portable=1 ;;
        --public-metadata) public_metadata=1 ;;
        --private-metadata) public_metadata=0 ;;
        *)
            printf 'Usage: %s [--portable] [--public-metadata|--private-metadata]\n' "$0" >&2
            exit 2
            ;;
    esac
done

need() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'MISSING REQUIRED QUALITY TOOL: %s\n' "$1" >&2
        return 1
    }
}

assert_clean_tree() {
    local transient
    transient="$(find . \
        \( -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \
            -o -name '.mypy_cache' -o -name '*.egg-info' -o -name '.venv' -o -name 'build' \) \
        -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
        -print -quit)"
    if [[ -n "${transient}" ]]; then
        printf 'Transient build/runtime artifact exists in release tree: %s\n' "${transient}" >&2
        exit 1
    fi
    if find . -type l -print -quit | grep -q .; then
        printf '%s\n' 'Release tree contains a symbolic link.' >&2
        find . -type l -print >&2
        exit 1
    fi
}

assert_manifest_inventory() {
    local manifest_inventory actual_inventory
    manifest_inventory="$(awk '{print substr($0, 67)}' SHA256SUMS | LC_ALL=C sort)"
    actual_inventory="$(find . -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort)"
    if [[ "${manifest_inventory}" != "${actual_inventory}" ]]; then
        printf '%s\n' 'Release-tree inventory differs from SHA256SUMS.' >&2
        diff -u \
            <(printf '%s\n' "${manifest_inventory}") \
            <(printf '%s\n' "${actual_inventory}") >&2 || true
        exit 1
    fi
}

qa_root=""
cleanup() {
    local status=$?
    trap - EXIT
    [[ -z "${qa_root}" || ! -d "${qa_root}" ]] || rm -rf -- "${qa_root}"
    exit "${status}"
}
trap cleanup EXIT
trap 'status=$?; printf "QUALITY GATE FAILED near line %s (exit %s): %s\n" "${LINENO}" "${status}" "${BASH_COMMAND}" >&2' ERR

printf '%s\n' '[Q1/9] Source syntax and static security/design policy'
if ! python3 -c 'import defusedxml.ElementTree' >/dev/null 2>&1; then
    printf '%s\n' 'MISSING REQUIRED QUALITY MODULE: defusedxml (Arch: python-defusedxml)' >&2
    exit 1
fi
python3 - <<'PY'
from pathlib import Path
for path in sorted(Path('.').rglob('*.py')):
    if any(part in {'__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache'} for part in path.parts):
        continue
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
print('Python syntax: PASS')
PY
python3 tools/verify_tree.py
assert_clean_tree

printf '%s\n' '[Q2/9] PEP 517/621 editable-install and import-boundary tests'
need python3
python3 -m pip --version >/dev/null
qa_root="$(mktemp -d)"
qa_source="${qa_root}/source"
qa_editable="${qa_root}/editable-venv"
qa_editable_target="${qa_root}/editable-target"
qa_wheel_venv="${qa_root}/wheel-venv"
qa_wheel_target="${qa_root}/wheel-target"
qa_wheels="${qa_root}/wheels"
qa_shadow="${qa_root}/shadow"
mkdir -p -- "${qa_source}" "${qa_editable_target}" "${qa_wheel_target}" "${qa_wheels}" "${qa_shadow}"
cp -a -- . "${qa_source}/tree"
qa_source="${qa_source}/tree"
printf '%s\n' 'raise RuntimeError("CWD shadow imported")' > "${qa_shadow}/verselatch_core.py"

if (( portable == 1 )); then
    # The hosted build container's interpreter lives inside its own base venv,
    # so a nested stdlib venv cannot inherit that venv's setuptools backend.
    # Use pip's isolated --target staging instead. Processing the generated
    # editable .pth with site.addsitedir() tests the PEP 660 artifact itself;
    # the exact Arch/native gate below uses a normal venv and editable install.
    python3 -m pip install \
        --disable-pip-version-check --no-deps --no-build-isolation \
        --target "${qa_editable_target}" -e "${qa_source}" >/dev/null
    (
        cd -- "${qa_source}"
        python3 - "${qa_editable_target}" <<'PY_EDITABLE_TESTS'
import site
import sys
site.addsitedir(sys.argv[1])
import pytest
raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider"]))
PY_EDITABLE_TESTS
    )
    python3 -I - "${qa_editable_target}" <<'PY_EDITABLE_IMPORT'
import pathlib
import site
import sys
site.addsitedir(sys.argv[1])
import verselatch_core
p = pathlib.Path(verselatch_core.__file__).resolve()
assert "src/verselatch_core" in p.as_posix(), p
print("Editable import boundary: PASS")
PY_EDITABLE_IMPORT
    (
        cd -- "${qa_shadow}"
        python3 -I - "${qa_editable_target}" <<'PY_EDITABLE_SHADOW'
import pathlib
import site
import sys
site.addsitedir(sys.argv[1])
import verselatch_core
p = pathlib.Path(verselatch_core.__file__).resolve()
assert "src/verselatch_core" in p.as_posix(), p
PY_EDITABLE_SHADOW
    )
else
    # Arch deliberately packages pip separately from Python. Build the test
    # environment without relying on ensurepip, expose distro QA modules, and
    # let the already-required system pip manage the venv through its documented
    # --python interface. Do not run a whole-environment dependency audit here:
    # with --system-site-packages it would inspect unrelated distro Python packages
    # rather than VerseLatch, which has no PyPI runtime dependencies.
    python3 -m venv --without-pip --system-site-packages "${qa_editable}"
    "${qa_editable}/bin/python" -c 'import setuptools.build_meta, pytest' >/dev/null || {
        printf '%s\n' 'Native QA venv cannot import setuptools/pytest; install the required Arch QA packages.' >&2
        exit 1
    }
    python3 -m pip --python "${qa_editable}" install \
        --disable-pip-version-check --no-deps --no-build-isolation -e "${qa_source}" >/dev/null
    (
        cd -- "${qa_source}"
        "${qa_editable}/bin/python" -m pytest -q -p no:cacheprovider
    )
    "${qa_editable}/bin/python" -I -c \
        'import verselatch_core, pathlib; p=pathlib.Path(verselatch_core.__file__).resolve(); assert "src/verselatch_core" in p.as_posix(), p; print("Editable import boundary: PASS")'
    (
        cd -- "${qa_shadow}"
        "${qa_editable}/bin/python" -I -c \
            'import verselatch_core, pathlib; p=pathlib.Path(verselatch_core.__file__).resolve(); assert "src/verselatch_core" in p.as_posix(), p'
    )
fi
printf '%s\n' 'CWD shadow resistance (editable): PASS'

printf '%s\n' '[Q3/9] Regular wheel build/install and wheel inventory'
python3 -m pip wheel \
    --disable-pip-version-check --no-deps --no-build-isolation \
    --wheel-dir "${qa_wheels}" "${qa_source}" >/dev/null
wheel="$(find "${qa_wheels}" -maxdepth 1 -type f -name 'verselatch-1.0.0-*.whl' -print -quit)"
[[ -n "${wheel}" ]]
python3 -I - "${wheel}" <<'PY_WHEEL'
import sys, zipfile
wheel = sys.argv[1]
with zipfile.ZipFile(wheel) as zf:
    names = set(zf.namelist())
required = {
    'verselatch.py',
    'verselatch_core/__init__.py',
    'verselatch_core/alignment.py',
    'verselatch_core/asr.py',
    'verselatch_core/constants.py',
    'verselatch_core/errors.py',
    'verselatch_core/lrc.py',
    'verselatch_core/process.py',
    'verselatch_core/rhythm.py',
    'verselatch_core/storage.py',
}
missing = required - names
assert not missing, sorted(missing)
for prefix in ('tests/', 'tools/', 'docs/', 'data/', 'packaging/'):
    assert not any(name.startswith(prefix) for name in names), prefix
metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
assert len(metadata) == 1, metadata
with zipfile.ZipFile(wheel) as zf:
    text = zf.read(metadata[0]).decode('utf-8')
assert 'License-Expression: GPL-3.0-only' in text
assert 'Requires-Python: >=3.10' in text
assert 'Classifier: Private :: Do Not Upload' not in text
assert 'Project-URL: Homepage, https://github.com/erhansavas/verselatch' in text
assert 'Project-URL: Repository, https://github.com/erhansavas/verselatch.git' in text
assert 'Project-URL: Issues, https://github.com/erhansavas/verselatch/issues' in text
print('Wheel inventory/metadata: PASS')
PY_WHEEL

if (( portable == 1 )); then
    python3 -m pip install \
        --disable-pip-version-check --no-deps --target "${qa_wheel_target}" "${wheel}" >/dev/null
    (
        cd -- "${qa_shadow}"
        python3 -I - "${qa_wheel_target}" <<'PY_WHEEL_IMPORT'
import pathlib
import site
import sys
site.addsitedir(sys.argv[1])
import verselatch_core
p = pathlib.Path(verselatch_core.__file__).resolve()
assert "verselatch_core" in p.as_posix(), p
assert "src/verselatch_core" not in p.as_posix(), p
PY_WHEEL_IMPORT
    )
else
    python3 -m venv --without-pip --system-site-packages "${qa_wheel_venv}"
    python3 -m pip --python "${qa_wheel_venv}" install \
        --disable-pip-version-check --no-deps "${wheel}" >/dev/null
    (
        cd -- "${qa_shadow}"
        "${qa_wheel_venv}/bin/python" -I -c \
            'import verselatch_core, pathlib; p=pathlib.Path(verselatch_core.__file__).resolve(); assert "site-packages/verselatch_core" in p.as_posix(), p'
    )
fi
printf '%s\n' 'Regular wheel install + CWD shadow resistance: PASS'

printf '%s\n' '[Q4/9] Package manifest'
sha256sum --strict -c SHA256SUMS
assert_manifest_inventory
assert_clean_tree

printf '%s\n' '[Q5/9] Shell syntax'
bash -n \
    packaging/linux/install-user.sh \
    packaging/linux/install-model.sh \
    packaging/linux/uninstall-user.sh \
    packaging/linux/verselatch \
    tools/native_release_check.sh \
    tools/public_release_check.sh \
    tools/quality_gate.sh \
    tools/validate_appstream.sh

if (( portable == 1 )); then
    printf '%s\n' '[Q6/9] Desktop/AppStream external validators: SKIP (portable mode)'
    printf '%s\n' '[Q7/9] ShellCheck/REUSE: SKIP (portable mode)'
    printf '%s\n' '[Q8/9] Ruff/Bandit: SKIP (portable mode)'
else
    printf '%s\n' '[Q6/9] Desktop/AppStream metadata'
    need desktop-file-validate
    desktop-file-validate data/io.github.erhansavas.verselatch.desktop
    if (( public_metadata == 1 )); then
        tools/validate_appstream.sh --public
    else
        tools/validate_appstream.sh --private
    fi

    printf '%s\n' '[Q7/9] Shell and licensing lint'
    need shellcheck
    shellcheck \
        packaging/linux/install-user.sh \
        packaging/linux/install-model.sh \
        packaging/linux/uninstall-user.sh \
        packaging/linux/verselatch \
        tools/native_release_check.sh \
        tools/public_release_check.sh \
        tools/quality_gate.sh \
        tools/validate_appstream.sh
    need reuse
    reuse lint

    printf '%s\n' '[Q8/9] Python lint/security analyzers'
    need ruff
    ruff check --no-cache src tests tools
    need bandit
    bandit -q -r src tools -x tests -ll
    printf '%s\n' 'Bandit medium/high-severity security scan: PASS'
fi

printf '%s\n' '[Q9/9] Final clean-tree safety scan'
assert_clean_tree
assert_manifest_inventory
if (( portable == 1 )); then
    printf '%s\n' 'PORTABLE QUALITY GATE: PASS (native external validators deferred)'
else
    printf '%s\n' 'NATIVE QUALITY GATE: PASS'
fi
