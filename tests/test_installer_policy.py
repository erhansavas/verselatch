# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP = SRC / "verselatch.py"
CORE = SRC / "verselatch_core"
PACKAGING = ROOT / "packaging" / "linux"
INSTALLER = PACKAGING / "install-user.sh"
UNINSTALLER = PACKAGING / "uninstall-user.sh"


def test_installer_stages_and_atomically_swaps_complete_modular_payload():
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"' in text
    assert 'CORE_SOURCE="${PROJECT_ROOT}/src/verselatch_core"' in text
    assert 'APP_STAGE="$(mktemp -d --tmpdir="${APP_ROOT}"' in text
    assert 'install -m 0755 -- "${SOURCE}" "${APP_STAGE}/verselatch.py"' in text
    assert '"${APP_STAGE}/verselatch_core/' in text
    assert 'mv -T -- "${TARGET_DIR}" "${APP_BACKUP}"' in text
    assert 'mv -T -- "${APP_STAGE}" "${TARGET_DIR}"' in text
    assert 'APP_BACKUP_MOVED=1' in text
    assert 'previous VerseLatch application payload restored' in text


def test_uninstaller_requires_verified_ownership_manifest_before_removal():
    text = UNINSTALLER.read_text(encoding="utf-8")
    assert "verselatch_validate_manifest \"${INSTALL_MANIFEST}\" '1.0.1'" in text
    assert 'ownership helper is missing or modified; refusing destructive uninstall' in text
    assert 'rm -rf --one-file-system -- "${TARGET_DIR}"' in text
    assert 'MODEL_DIR="${DATA_HOME}/verselatch/models"' in text
    assert 'Retained intentionally:' in text
    assert 'LRC files next to your audio are never removed.' in text


def test_installer_requires_every_shipped_core_module():
    root = CORE
    installer = INSTALLER.read_text(encoding="utf-8")
    for module in sorted(root.glob("*.py")):
        assert f'"${{CORE_SOURCE}}/{module.name}"' in installer


def test_installer_main_source_hash_matches_current_payload():
    import hashlib
    import re

    source = APP
    installer = INSTALLER.read_text(encoding="utf-8")
    match = re.search(r'^EXPECTED_SHA256="([0-9a-f]{64})"$', installer, re.MULTILINE)
    assert match is not None
    assert match.group(1) == hashlib.sha256(source.read_bytes()).hexdigest()


def test_installer_home_validation_is_auditable_and_shellcheck_suppression_free():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "DESKTOP_EXEC_FORBIDDEN_CHARS" in text
    assert 'for forbidden_character in "${DESKTOP_EXEC_FORBIDDEN_CHARS[@]}"' in text
    for literal in ("$'\\n'", "$'\\r'", "'\"'", "'`'", "'$'", "'%'", "'='"):
        assert literal in text
    assert "shellcheck disable=" not in text
    assert "*$'\\n'*|*$'\\r'*" not in text


def test_installer_prints_literal_path_guidance_without_single_quote_expansion_pattern():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "printf '%s\\n' \"  export PATH=\\\"\\$HOME/.local/bin:\\$PATH\\\"\"" in text
    assert "printf '  export PATH=\"" not in text


def test_installer_uses_exact_gpl3_only_gtk_and_public_appstream_metadata():
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'hasattr(Gtk.License, "GPL_3_0_ONLY")' in text
    assert '<metadata_license>MIT</metadata_license>' in text
    assert '<project_license>GPL-3.0-only</project_license>' in text
    assert '<release version="1.0.1" date="2026-08-13">' in text
    assert '<release version="1.0.0" date="2026-08-12">' in text
    assert '<url type="homepage">https://github.com/erhansavas/verselatch</url>' in text
    assert "if 'type=\"development\"' in text" in text
    assert "AppStream MetaInfo public-release structure: OK" in text
    assert 'hasattr(Gtk.License, "GPL_3_0")' not in text


def test_installer_prevents_test_generated_payload_files_from_being_installed():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "expected_stage_inventory" in text
    assert "actual_stage_inventory" in text
    assert "ERROR: staged application payload changed during tests." in text
    assert 'python3 -E -s -B "${APP_STAGE}/verselatch.py" --self-test' in text
    assert 'python3 -E -s -B "${APP_STAGE}/verselatch.py" --smoke-test' in text


def test_personal_desktop_tryexec_is_unquoted_and_gio_registration_is_transactional():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "TryExec=${LAUNCHER}" in text
    assert 'TryExec="${LAUNCHER}"' not in text
    assert 'Exec="${LAUNCHER}"' in text
    assert "Desktop/GIO application registration: OK" in text
    assert "Gio.AppInfo.get_all()" in text
    assert "app.should_show()" in text
    assert "try_exec != launcher_path" in text
    assert "os.access(launcher_path, os.X_OK)" in text


def test_gio_registration_compares_launch_semantics_not_debug_executable_text():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "commandline = app.get_commandline()" in text
    assert "argv = shlex.split(commandline, posix=True)" in text
    assert "if argv != [launcher_path]:" in text
    assert "app.get_executable() != launcher_path" not in text


def test_installer_preflight_matches_current_libadwaita_ui_api_floor():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "if adw < (1, 8):" in text
    assert "libadwaita 1.8+ required" in text
    for api in (
        '"PreferencesGroup"',
        '"ActionRow"',
        '"EntryRow"',
        '"ButtonRow"',
        '"ShortcutsDialog"',
        '"ShortcutsSection"',
        '"ShortcutsItem"',
    ):
        assert api in text


def test_model_download_is_explicit_and_shows_terminal_progress():
    installer = INSTALLER.read_text(encoding="utf-8")
    model_installer = (PACKAGING / "install-model.sh").read_text(encoding="utf-8")
    for text in (installer, model_installer):
        assert "1.51 GiB" in text
        assert "--progress-bar" in text
        assert "Verifying model integrity" in text
        assert "Press Ctrl+C to cancel safely" in text
    assert "Verified models are reused on later installs" in installer
    assert "existing verified model is reused" in model_installer


def _run_ownership_helper(tmp_path: Path, body: str):
    import os
    import shlex
    import subprocess

    home = tmp_path / "home"
    data = home / ".local/share"
    app_root = data / "verselatch"
    q = shlex.quote
    env = os.environ.copy()
    env.update({"HOME": str(home), "XDG_DATA_HOME": str(data)})
    setup = f"""
set -Eeuo pipefail
PATH=/usr/bin:/bin
APP_ROOT={q(str(app_root))}
TARGET_DIR="$APP_ROOT/app"
APP="$TARGET_DIR/verselatch.py"
LAUNCHER={q(str(home / '.local/bin/verselatch'))}
UNINSTALLER={q(str(home / '.local/bin/verselatch-uninstall'))}
DESKTOP={q(str(data / 'applications/io.github.erhansavas.verselatch.desktop'))}
ICON={q(str(data / 'icons/hicolor/scalable/apps/io.github.erhansavas.verselatch.svg'))}
SYMBOLIC_ICON={q(str(data / 'icons/hicolor/symbolic/apps/io.github.erhansavas.verselatch-symbolic.svg'))}
METAINFO={q(str(data / 'metainfo/io.github.erhansavas.verselatch.metainfo.xml'))}
OWNERSHIP_LIB="$APP_ROOT/install-ownership.sh"
INSTALL_MANIFEST="$APP_ROOT/install-manifest.tsv"
source {q(str(PACKAGING / 'install-ownership.sh'))}
{body}
"""
    return subprocess.run(["/usr/bin/bash", "-c", setup], env=env, text=True, capture_output=True)

def test_foreign_launcher_collision_is_refused_and_preserved(tmp_path: Path):
    launcher = tmp_path / "home/.local/bin/verselatch"
    launcher.parent.mkdir(parents=True)
    original = b"foreign user data\n"
    launcher.write_bytes(original)
    result = _run_ownership_helper(tmp_path, "verselatch_preflight_install_ownership")
    assert result.returncode != 0
    assert launcher.read_bytes() == original
    assert "refusing to overwrite" in result.stderr


def test_manifest_detects_modified_launcher_and_extra_app_file(tmp_path: Path):
    result = _run_ownership_helper(
        tmp_path,
        r'''
mkdir -p "$TARGET_DIR/verselatch_core" "$(dirname "$LAUNCHER")" "$(dirname "$UNINSTALLER")" \
  "$(dirname "$DESKTOP")" "$(dirname "$ICON")" "$(dirname "$SYMBOLIC_ICON")" "$(dirname "$METAINFO")"
printf app > "$APP"; printf core > "$TARGET_DIR/verselatch_core/__init__.py"
printf launcher > "$LAUNCHER"; printf uninstall > "$UNINSTALLER"; printf desktop > "$DESKTOP"
printf icon > "$ICON"; printf symbolic > "$SYMBOLIC_ICON"; printf meta > "$METAINFO"; printf helper > "$OWNERSHIP_LIB"
verselatch_write_manifest "$INSTALL_MANIFEST" 1.0.1
printf foreign-change > "$LAUNCHER"
if verselatch_validate_manifest "$INSTALL_MANIFEST" 1.0.1; then exit 90; fi
printf launcher > "$LAUNCHER"
printf foreign > "$TARGET_DIR/foreign.txt"
if verselatch_validate_manifest "$INSTALL_MANIFEST" 1.0.1; then exit 91; fi
''',
    )
    assert result.returncode == 0, result.stderr


def test_clean_manifest_validates_and_retained_paths_are_outside_managed_tree(tmp_path: Path):
    result = _run_ownership_helper(
        tmp_path,
        r'''
mkdir -p "$TARGET_DIR/verselatch_core" "$(dirname "$LAUNCHER")" "$(dirname "$UNINSTALLER")" \
  "$(dirname "$DESKTOP")" "$(dirname "$ICON")" "$(dirname "$SYMBOLIC_ICON")" "$(dirname "$METAINFO")" "$APP_ROOT/models"
printf app > "$APP"; printf core > "$TARGET_DIR/verselatch_core/__init__.py"
printf launcher > "$LAUNCHER"; printf uninstall > "$UNINSTALLER"; printf desktop > "$DESKTOP"
printf icon > "$ICON"; printf symbolic > "$SYMBOLIC_ICON"; printf meta > "$METAINFO"; printf helper > "$OWNERSHIP_LIB"
printf model > "$APP_ROOT/models/model.bin"
verselatch_write_manifest "$INSTALL_MANIFEST" 1.0.1
verselatch_validate_manifest "$INSTALL_MANIFEST" 1.0.1
''',
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "home/.local/share/verselatch/models/model.bin").read_bytes() == b"model"


def test_transaction_cleanup_restores_exact_preinstall_state_after_forced_failure(tmp_path: Path):
    """Exercise the shipped cleanup() body with a synthetic failed transaction."""
    import os
    import shlex
    import subprocess

    installer_text = INSTALLER.read_text(encoding="utf-8")
    start = installer_text.index("cleanup() {\n")
    end = installer_text.index("trap cleanup EXIT", start)
    cleanup_definition = installer_text[start:end]

    root = tmp_path / "tx"
    target = root / "app"
    app_backup = root / ".app.backup"
    launcher = root / "bin/verselatch"
    launcher_backup = root / "launcher-backup"
    ownership = root / "install-ownership.sh"
    ownership_backup = root / "ownership-backup"
    manifest = root / "install-manifest.tsv"
    manifest_backup = root / "manifest-backup"
    for directory in (
        target,
        app_backup,
        launcher.parent,
        launcher_backup,
        ownership_backup,
        manifest_backup,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (target / "new").write_bytes(b"new-app\n")
    (app_backup / "old").write_bytes(b"old-app\n")
    launcher.write_bytes(b"new-launcher\n")
    (launcher_backup / "original").write_bytes(b"old-launcher\n")
    ownership.write_bytes(b"new-helper\n")
    (ownership_backup / "original").write_bytes(b"old-helper\n")
    manifest.write_bytes(b"new-manifest\n")
    (manifest_backup / "original").write_bytes(b"old-manifest\n")

    q = shlex.quote
    script = f"""
set -Eeuo pipefail
{cleanup_definition}
ASR_MODEL_STAGE=''; RHYTHM_SMOKE_DIR=''; APP_STAGE=''; LAUNCHER_STAGE=''; UNINSTALLER_STAGE=''
DESKTOP_STAGE=''; ICON_STAGE=''; SYMBOLIC_ICON_STAGE=''; METAINFO_STAGE=''; OWNERSHIP_STAGE=''; MANIFEST_STAGE=''
TARGET_DIR={q(str(target))}; APP_BACKUP={q(str(app_backup))}; APP_HAD=1; APP_BACKUP_MOVED=1; APP_REPLACED=1
LAUNCHER={q(str(launcher))}; LAUNCHER_BACKUP_DIR={q(str(launcher_backup))}; LAUNCHER_HAD=1; LAUNCHER_REPLACED=1
UNINSTALLER=''; UNINSTALLER_BACKUP_DIR=''; UNINSTALLER_HAD=0; UNINSTALLER_REPLACED=0
DESKTOP=''; DESKTOP_BACKUP_DIR=''; DESKTOP_HAD=0; DESKTOP_REPLACED=0
ICON=''; ICON_BACKUP_DIR=''; ICON_HAD=0; ICON_REPLACED=0
SYMBOLIC_ICON=''; SYMBOLIC_ICON_BACKUP_DIR=''; SYMBOLIC_ICON_HAD=0; SYMBOLIC_ICON_REPLACED=0
METAINFO=''; METAINFO_BACKUP_DIR=''; METAINFO_HAD=0; METAINFO_REPLACED=0
OWNERSHIP_LIB={q(str(ownership))}; OWNERSHIP_BACKUP_DIR={q(str(ownership_backup))}; OWNERSHIP_HAD=1; OWNERSHIP_REPLACED=1
INSTALL_MANIFEST={q(str(manifest))}; MANIFEST_BACKUP_DIR={q(str(manifest_backup))}; MANIFEST_HAD=1; MANIFEST_REPLACED=1
set +e
false
cleanup
"""
    result = subprocess.run(
        ["/usr/bin/bash", "-c", script],
        env=os.environ.copy(),
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert not (target / "new").exists()
    assert (target / "old").read_bytes() == b"old-app\n"
    assert launcher.read_bytes() == b"old-launcher\n"
    assert ownership.read_bytes() == b"old-helper\n"
    assert manifest.read_bytes() == b"old-manifest\n"
