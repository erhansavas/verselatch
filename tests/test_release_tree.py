# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from pathlib import Path
import ast
import xml.etree.ElementTree as ET

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP = SRC / "verselatch.py"
PACKAGING = ROOT / "packaging" / "linux"
INSTALLER = PACKAGING / "install-user.sh"
UNINSTALLER = PACKAGING / "uninstall-user.sh"
APP_ID = "io.github.erhansavas.verselatch"
SPDX_LICENSE_TAG = "SPDX-" + "License-Identifier:"
SPDX_COPYRIGHT_TAG = "SPDX-" + "FileCopyrightText:"
REUSE_IGNORE_START = "REUSE-" + "IgnoreStart"
REUSE_IGNORE_END = "REUSE-" + "IgnoreEnd"


def test_app_parses_without_importing_gtk():
    ast.parse(APP.read_text(encoding="utf-8"))


def test_metadata_xml_is_well_formed_and_public_release_safe():
    meta = ROOT / f"data/{APP_ID}.metainfo.xml"
    ET.parse(meta)
    ET.parse(ROOT / f"data/{APP_ID}.svg")
    ET.parse(ROOT / f"data/{APP_ID}-symbolic.svg")
    text = meta.read_text(encoding="utf-8")
    assert "<metadata_license>MIT</metadata_license>" in text
    assert "<project_license>GPL-3.0-only</project_license>" in text
    assert "<summary>Create and align LRC timing</summary>" in text
    assert '<developer id="io.github.erhansavas">' in text
    assert '<url type="homepage">https://github.com/erhansavas/verselatch</url>' in text
    assert '<url type="bugtracker">https://github.com/erhansavas/verselatch/issues</url>' in text
    assert '<release version="1.0.1" date="2026-08-13">' in text
    assert '<release version="1.0.0" date="2026-08-12">' in text
    assert 'type="development"' not in text


def test_license_family_is_consistent():
    assert (ROOT / "LICENSES/GPL-3.0-only.txt").is_file()
    for stale in (
        "LICENSES/GPL-3.0-or-later.txt",
        "LICENSES/AGPL-3.0-only.txt",
        "LICENSES/AGPL-3.0-or-later.txt",
    ):
        assert not (ROOT / stale).exists()
    for rel in (
        "src/verselatch.py",
        "packaging/linux/install-user.sh",
        "packaging/linux/install-model.sh",
        "packaging/linux/install-ownership.sh",
        "packaging/linux/uninstall-user.sh",
        "tools/verify_tree.py",
        "tools/release.py",
        "tools/native_release_check.sh",
        "packaging/linux/verselatch",
    ):
        head = "\n".join((ROOT / rel).read_text(encoding="utf-8").splitlines()[:8])
        assert f"{SPDX_LICENSE_TAG} GPL-3.0-only" in head
        assert f"{SPDX_LICENSE_TAG} AGPL-3.0-only" not in head
        assert f"{SPDX_LICENSE_TAG} AGPL-3.0-or-later" not in head


def test_about_is_single_source_of_truth_for_privacy_and_legal_ui():
    source = APP.read_text(encoding="utf-8")
    assert "license_type=Gtk.License.GPL_3_0_ONLY" in source
    assert "license_type=Gtk.License.GPL_3_0," not in source
    assert '"AppStream metadata — MIT"' in source
    assert "Gtk.License.CUSTOM" in source
    assert "The AppStream metadata is licensed under the MIT License." in source
    assert "Gtk.License.MIT_X11" not in source
    assert source.count("does not send telemetry") == 1
    assert source.count("background service") == 1
    assert "Local processing ·" not in source
    assert "Source → Analyze → Review → Save" not in source
    assert "Lyrics that fit the recording." not in source
    assert "Legal & About" not in source


def test_workbench_uses_native_semantics_without_header_theme_chrome():
    source = APP.read_text(encoding="utf-8")
    assert 'label="Create and Align LRC Files"' not in source
    assert 'intro_title = Gtk.Label(label="Create LRC")' in source
    assert 'self.set_default_size(\n            800,\n            600,\n        )' in source
    assert 'Choose audio, then add lyrics to align or leave them empty' in source
    assert 'input_group = Adw.PreferencesGroup()' in source
    assert 'Adw.ActionRow(' in source
    assert 'Adw.EntryRow(title="Language")' in source
    assert 'self.analyze_button = Gtk.Button(label="Generate Draft")' in source
    assert 'self.analyze_button.add_css_class("pill")' in source
    assert 'label="Lyrics and timestamps reviewed"' in source
    assert 'footer = Gtk.Label(label="GPL-3.0-only · © 2026 erhansavas")' in source
    assert 'page.append(footer)' in source
    assert 'content.append(footer)' not in source
    assert 'menu_button.set_primary(True)' in source
    assert 'toolbar.set_top_bar_style(Adw.ToolbarStyle.FLAT)' in source
    assert 'self.status_label = Gtk.Label(label="Choose an audio file to begin")' in source
    assert 'self.clear_button.add_css_class("flat")' in source
    assert 'Adw.PreferencesGroup(title="Source")' not in source
    assert 'Adw.PreferencesGroup(title="Analysis")' not in source
    assert 'self.status_row = Adw.ActionRow(' not in source
    assert '"Keyboard Shortcuts"' in source
    assert 'Adw.ShortcutsDialog()' in source
    assert 'DEFAULT_THEME = "system"' in source
    assert '("Follow System", "system")' in source
    assert '("Light", "light")' in source
    assert '("Dark", "dark")' in source
    assert '"Dark Gray", "gray"' not in source
    assert '"Pure Black", "black"' not in source
    assert "THEME_PALETTES" not in source
    assert "theme_dropdown" not in source
    assert "--window-bg-color:" not in source
    assert "--accent-bg-color:" not in source
    assert "--accent-fg-color:" not in source
    assert "font-size:" not in source
    assert "Leave blank for automatic detection" in source
    assert 'Gtk.Label(label="tr, en, ru")' in source
    assert 'self.language_entry.add_suffix(self.language_example)' in source
    assert 'not busy and not bool(self.language_entry.get_text().strip())' in source
    assert "Analysis runs locally and can take several minutes on CPU" in source
    assert "Selected lyric words remain unchanged unless edited in the preview." in source
    assert "auto-detect" not in source
    assert "same-name lyrics" not in source
    assert "welcome_card" not in source
    assert "Audio is required; lyrics are optional" not in source
    assert "io.github.erhansavas.verselatch.metainfo.xml" not in source[source.index("    def show_about("):source.index("    def build_ui(")]

    helper = source[source.index("    def refresh_primary_action_style("):source.index("    def set_analysis_action(")]
    assert 'self.analyze_button.remove_css_class("suggested-action")' in helper
    assert 'self.save_button.remove_css_class("suggested-action")' in helper
    assert helper.count('add_css_class("suggested-action")') == 2
    assert source.count('add_css_class("suggested-action")') == 2


def test_installed_self_test_owns_its_css_validation_state():
    source = APP.read_text(encoding="utf-8")
    block = source[source.index("def self_test():"):source.index("\ndef main():")]
    assert "css_provider = Gtk.CssProvider()" in block
    assert "css_errors: list[str] = []" in block
    assert 'css_provider.connect("parsing-error", record_css_error)' in block
    assert "css_provider.load_from_string(css)" in block
    assert "\n    provider.load_from_string" not in block


def test_application_imports_public_core_interfaces_only():
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("verselatch_core"):
            assert all(not alias.name.startswith("_") for alias in node.names)


def test_personal_installer_owns_desktop_metadata_symmetrically():
    installer = INSTALLER.read_text(encoding="utf-8")
    uninstaller = UNINSTALLER.read_text(encoding="utf-8")
    for token in (
        "io.github.erhansavas.verselatch.desktop",
        "io.github.erhansavas.verselatch.svg",
        "io.github.erhansavas.verselatch-symbolic.svg",
        "io.github.erhansavas.verselatch.metainfo.xml",
    ):
        assert token in installer
        assert token in uninstaller


def test_no_bundled_fonts_or_model_payload():
    assert not [p for p in ROOT.rglob("*") if p.suffix.lower() in {".ttf", ".otf", ".woff", ".woff2"}]
    assert not [p for p in ROOT.rglob("ggml-*.bin")]


def test_no_stale_first_party_spdx_license_family_remains():
    stale_headers = (
        f"{SPDX_LICENSE_TAG} GPL-3.0-or-later",
        f"{SPDX_LICENSE_TAG} AGPL-3.0-only",
        f"{SPDX_LICENSE_TAG} AGPL-3.0-or-later",
    )
    for path in ROOT.rglob("*"):
        if not path.is_file() or "LICENSES" in path.parts:
            continue
        try:
            head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        except UnicodeDecodeError:
            continue
        for header in stale_headers:
            assert header not in head, f"{header} in {path.relative_to(ROOT)}"


def test_reuse_fixture_scans_cannot_misread_embedded_spdx_test_strings():
    for relative in ("tests/test_release_tree.py", "tools/verify_tree.py"):
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        occurrences = [index for index, line in enumerate(lines, start=1) if SPDX_LICENSE_TAG in line]
        assert len(occurrences) == 1, f"unexpected embedded SPDX license tag in {relative}: {occurrences}"
        assert occurrences[0] <= 8, f"SPDX license tag is not confined to the file header in {relative}"


def test_quality_gates_keep_ruff_cache_out_of_reuse_input():
    native = (ROOT / "tools/native_release_check.sh").read_text(encoding="utf-8")
    quality = (ROOT / "tools/quality_gate.sh").read_text(encoding="utf-8")
    assert "RUFF_NO_CACHE=1" in native
    assert "RUFF_NO_CACHE=1" in quality
    assert "ruff check --no-cache" in quality
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in quality
    assert "public_metadata=1" in quality
    assert "need bandit" in quality
    assert "bandit -q -r src tools -x tests -ll" in quality
    assert "MISSING OPTIONAL QUALITY TOOL: bandit" not in quality
    assert "--exit-zero" not in quality
    assert "python3 -m venv --without-pip --system-site-packages" in quality
    assert 'python3 -m pip --python "${qa_editable}" install' in quality
    assert 'python3 -m pip --python "${qa_wheel_venv}" install' in quality
    assert "pip check" not in quality
    assert "QUALITY GATE FAILED near line" in quality
    assert "quality_gate.sh" in native
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".ruff_cache/" in ignored
    assert ".pytest_cache/" in ignored
    assert "__pycache__/" in ignored


def test_isolated_application_runs_disable_bytecode_writes():
    native = (ROOT / "tools/native_release_check.sh").read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    system_launcher = (ROOT / "packaging/linux/verselatch").read_text(encoding="utf-8")

    assert "python3 -E -s -B src/verselatch.py --self-test" in native
    assert "python3 -E -s -B src/verselatch.py --smoke-test" in native
    assert 'python3 -E -s -B "${APP_STAGE}/verselatch.py" --self-test' in installer
    assert 'python3 -E -s -B "${APP_STAGE}/verselatch.py" --smoke-test' in installer
    assert r'python3 -E -s -B "\${APP}" "\$@"' in installer
    assert 'exec /usr/bin/python3 -E -s -B "${APP}" "$@"' in system_launcher
    assert "Staged application inventory: OK" in installer
    assert "quality_gate.sh" in native


def test_nonheader_spdx_examples_are_explicitly_ignored_by_reuse():
    tags = (SPDX_LICENSE_TAG, SPDX_COPYRIGHT_TAG)
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "LICENSES" in path.parts or path.name == "LICENSE":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        ignore_depth = 0
        for index, line in enumerate(lines, start=1):
            if REUSE_IGNORE_START in line:
                ignore_depth += 1
            if index > 8 and any(tag in line for tag in tags):
                assert ignore_depth > 0, f"unignored SPDX-like example in {path.relative_to(ROOT)}:{index}"
            if REUSE_IGNORE_END in line:
                assert ignore_depth > 0, f"unmatched REUSE ignore-end marker in {path.relative_to(ROOT)}:{index}"
                ignore_depth -= 1
        assert ignore_depth == 0, f"unclosed REUSE ignore block in {path.relative_to(ROOT)}"


def test_repository_uses_src_layout_and_sparse_root_docs():
    assert APP.is_file()
    assert (SRC / "verselatch_core").is_dir()
    assert not (ROOT / "verselatch.py").exists()
    assert not (ROOT / "verselatch_core").exists()
    assert sorted(path.name for path in ROOT.glob("*.md")) == ["README.md"]
    assert (ROOT / "docs/ARCHITECTURE.md").is_file()
    assert (ROOT / ".github/SECURITY.md").is_file()


def test_pep621_metadata_and_src_package_discovery_are_explicit():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["build-system"]["build-backend"] == "setuptools.build_meta"
    assert any(value.startswith("setuptools>=77.0.3") for value in config["build-system"]["requires"])
    assert config["project"]["name"] == "verselatch"
    assert config["project"]["version"] == "1.0.1"
    assert config["project"]["license"] == "GPL-3.0-only"
    assert "classifiers" not in config["project"]
    assert config["project"]["urls"] == {
        "Homepage": "https://github.com/erhansavas/verselatch",
        "Repository": "https://github.com/erhansavas/verselatch.git",
        "Issues": "https://github.com/erhansavas/verselatch/issues",
    }
    assert "dependencies" not in config["project"]
    assert config["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--import-mode=importlib" in addopts
    assert "--strict-config" in addopts
    assert "--strict-markers" in addopts
    assert "--disable-plugin-autoload" in addopts
    assert "security" in config["dependency-groups"]
    assert any(value.startswith("bandit>=1.9") for value in config["dependency-groups"]["security"])


def test_release_text_hygiene_and_local_markdown_links():
    import re

    text_suffixes = {".py", ".sh", ".md", ".toml", ".yml", ".yaml", ".xml", ".desktop", ".txt"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or (path.suffix not in text_suffixes and path.name != ".gitignore"):
            continue
        data = path.read_bytes()
        assert b"\r\n" not in data, path.relative_to(ROOT)
        text = data.decode("utf-8")
        assert all(not line.endswith((" ", "\t")) for line in text.splitlines()), path.relative_to(ROOT)

    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    docs = [ROOT / "README.md", ROOT / ".github/SECURITY.md", *sorted((ROOT / "docs").glob("*.md"))]
    for path in docs:
        for target in link_pattern.findall(path.read_text(encoding="utf-8")):
            target = target.strip().strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = target.split("#", 1)[0]
            if relative:
                resolved = (path.parent / relative).resolve()
                resolved.relative_to(ROOT.resolve())
                assert resolved.exists(), f"{path.relative_to(ROOT)} -> {target}"


def test_python_sources_do_not_contain_blank_line_spam():
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "\n\n\n\n" not in text, path


def test_release_tree_contains_no_email_addresses():
    import re

    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    for path in ROOT.rglob("*"):
        if not path.is_file() or "LICENSES" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert email.search(text) is None, f"email address embedded in {path.relative_to(ROOT)}"


def test_no_source_test_or_tool_mutates_python_import_path():
    for base in (ROOT / "src", ROOT / "tests", ROOT / "tools"):
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("sys.path." + "insert", "sys.path." + "append", "sys.path." + "extend", "site." + "addsitedir"):
                assert forbidden not in text, f"{forbidden} in {path.relative_to(ROOT)}"


def test_public_release_check_validates_public_tree_and_endpoints():
    text = (ROOT / "tools/public_release_check.sh").read_text(encoding="utf-8")
    assert 'HOMEPAGE="https://github.com/erhansavas/verselatch"' in text
    assert 'BUGTRACKER="https://github.com/erhansavas/verselatch/issues"' in text
    assert "tools/validate_appstream.sh --public" in text
    assert "--proto '=https'" in text
    assert "--proto-redir '=https'" in text
    assert "--fail" in text
    assert "--max-time 20" in text
    assert "PUBLIC RELEASE CHECK: PASS" in text
    assert "complete native and manual acceptance gates" in text

def test_release_tree_verifier_uses_defusedxml_for_xml_parsing() -> None:
    verifier = (ROOT / "tools" / "verify_tree.py").read_text(encoding="utf-8")
    assert "from defusedxml import ElementTree as ET" in verifier
    assert "import xml.etree.ElementTree" not in verifier
    assert "# nosec B314" not in verifier


def test_defusedxml_rejects_entity_expansion_payload() -> None:
    from defusedxml import ElementTree as SafeET
    from defusedxml.common import DefusedXmlException

    payload = '<!DOCTYPE svg [<!ENTITY x "boom">]><svg>&x;</svg>'
    try:
        SafeET.fromstring(payload)
    except DefusedXmlException:
        pass
    else:
        raise AssertionError("defusedxml accepted an entity declaration")


def test_public_identity_uses_handle_not_personal_display_name():
    source = APP.read_text(encoding="utf-8")
    meta = (ROOT / f"data/{APP_ID}.metainfo.xml").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'developer_name="erhansavas"' in source
    assert 'copyright="© 2026 erhansavas"' in source
    assert '<name>erhansavas</name>' in meta
    assert '{ name = "erhansavas" }' in project
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.name in {"GPL-3.0-only.txt", "MIT.txt", "SHA256SUMS"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        removed_name = "Erhan" + " " + "Savaş"
        assert removed_name not in text, path


def test_language_and_publication_copy_stays_synchronized_with_behavior():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    invariants = (ROOT / "docs/INVARIANTS.md").read_text(encoding="utf-8")
    quality = (ROOT / "docs/QUALITY.md").read_text(encoding="utf-8")
    assert "short Whisper language code" in readme
    assert "does not expect full names" in readme
    assert "canonical public repository" in readme
    assert "without changing release bytes" not in readme
    assert "Public AppStream metadata" in invariants
    assert "strict public AppStream profile" in quality


def test_ci_is_minimal_portable_and_pins_action_dependencies():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "pull_request_target" not in workflow
    assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in workflow
    assert "persist-credentials: false" in workflow
    assert "secrets." not in workflow
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405" in workflow
    assert "./tools/quality_gate.sh --portable --public-metadata" in workflow
    assert "./tools/validate_appstream.sh --public" in workflow
    assert "shellcheck packaging/linux/*.sh tools/*.sh" in workflow
    assert "reuse lint" in workflow
    assert "ruff check --no-cache src tests tools" in workflow
    assert "bandit -q -r src tools -x tests -ll" in workflow
    assert "native_release_check.sh" not in workflow
