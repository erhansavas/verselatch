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


def test_uninstaller_removes_only_owned_app_payload_and_retains_user_data():
    text = UNINSTALLER.read_text(encoding="utf-8")
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
