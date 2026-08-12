#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import stat
import tomllib
from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP = SRC / "verselatch.py"
CORE = SRC / "verselatch_core"
DOCS = ROOT / "docs"
PACKAGING = ROOT / "packaging" / "linux"
MODEL_SHA = "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"
MODEL_SIZE = "1624555275"
PINNED_REVISION = "98aa99a0a9db05ae2342309f5096248665f7cba3"
APP_ID = "io.github.erhansavas.verselatch"
SPDX_LICENSE_TAG = "SPDX-" + "License-Identifier:"
SPDX_COPYRIGHT_TAG = "SPDX-" + "FileCopyrightText:"

BANNED_RUNTIME_MODULES = {
    "aiohttp", "ftplib", "http", "requests", "smtplib", "socket", "urllib", "websockets",
}
FORBIDDEN_RELEASE_SUFFIXES = {
    ".bin", ".gguf", ".pt", ".pth", ".onnx",
    ".ttf", ".otf", ".woff", ".woff2",
    ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac",
    ".exe", ".dll", ".so", ".dylib",
}
MAX_NORMAL_RELEASE_FILE = 10 * 1024 * 1024
IGNORED_PARTS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", ".venv", "build", "dist",
}


def fail(message: str) -> None:
    raise SystemExit("VERIFY FAIL: " + message)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"could not read {path.relative_to(ROOT)} as UTF-8: {exc}")


def parse_python(path: Path) -> tuple[str, ast.AST]:
    text = read(path)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        fail(f"Python syntax error in {path.relative_to(ROOT)}: {exc}")
    return text, tree


def regular_release_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in rel.parts):
            continue
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            fail(f"cannot stat {rel}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"release tree contains symlink: {rel}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(mode):
            fail(f"release tree contains special file: {rel}")
        files.append(path)
    return files


release_files = regular_release_files()

# Text hygiene and documentation navigation are release invariants. Keeping
# these checks in the static gate prevents small editorial regressions from
# bypassing review merely because they do not affect Python execution.
TEXT_SUFFIXES = {".py", ".sh", ".md", ".toml", ".yml", ".yaml", ".xml", ".desktop", ".txt"}
for path in release_files:
    if path.suffix.casefold() not in TEXT_SUFFIXES and path.name != ".gitignore":
        continue
    data = path.read_bytes()
    if b"\r\n" in data:
        fail(f"CRLF line endings in text file: {path.relative_to(ROOT)}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"text file is not UTF-8: {path.relative_to(ROOT)}: {exc}")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.endswith((" ", "\t")):
            fail(f"trailing whitespace in {path.relative_to(ROOT)}:{line_number}")

email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
for path in release_files:
    if "LICENSES" in path.parts:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if email_pattern.search(text):
        fail(f"email address embedded in release tree: {path.relative_to(ROOT)}")

markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
for path in (ROOT / "README.md", *sorted(DOCS.glob("*.md")), ROOT / ".github" / "SECURITY.md"):
    text = read(path)
    for target in markdown_link.findall(text):
        target = target.strip().strip("<>")
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        resolved = (path.parent / target_path).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            fail(f"Markdown link escapes repository in {path.relative_to(ROOT)}: {target}")
        if not resolved.exists():
            fail(f"broken Markdown link in {path.relative_to(ROOT)}: {target}")

# Root layout is intentionally sparse. Release integrity files and SPDX/REUSE
# metadata remain root-level because they describe the whole source artifact.
root_markdown = sorted(path.name for path in ROOT.glob("*.md"))
if root_markdown != ["README.md"]:
    fail(f"root Markdown clutter present: {root_markdown!r}")
for stale in (
    "COPYING",
    "verselatch.py",
    "verselatch_core",
    "install_verselatch_1.0.0.sh",
    "install_verselatch_model.sh",
    "uninstall_verselatch.sh",
):
    if (ROOT / stale).exists():
        fail(f"stale pre-refactor root path present: {stale}")
for required_dir in (SRC, CORE, DOCS, PACKAGING, ROOT / "LICENSES", ROOT / ".github"):
    if not required_dir.is_dir() or required_dir.is_symlink():
        fail(f"required project directory missing or unsafe: {required_dir.relative_to(ROOT)}")
for required_doc in (
    "ARCHITECTURE.md", "AUDIT_REPORT.md", "BRAND.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "DEPENDENCIES.md", "DESIGN_NOTES.md", "INVARIANTS.md", "LICENSING.md", "MIGRATION.md",
    "PRIVACY.md", "PROVENANCE.md", "PUBLICATION.md", "QUALITY.md", "RELEASE_CHECKLIST.md",
    "SYSTEM_REQUIREMENTS.md", "THIRD_PARTY_NOTICES.txt",
):
    if not (DOCS / required_doc).is_file():
        fail(f"documentation file missing after docs refactor: docs/{required_doc}")
if not (ROOT / ".github" / "SECURITY.md").is_file():
    fail("GitHub security policy must live at .github/SECURITY.md")

# PEP 517/621 packaging boundary.
try:
    pyproject = tomllib.loads(read(ROOT / "pyproject.toml"))
except tomllib.TOMLDecodeError as exc:
    fail(f"invalid pyproject.toml: {exc}")
build_system = pyproject.get("build-system", {})
project = pyproject.get("project", {})
setuptools_cfg = pyproject.get("tool", {}).get("setuptools", {})
pytest_cfg = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
if build_system.get("build-backend") != "setuptools.build_meta":
    fail("pyproject build backend must be setuptools.build_meta")
requires = build_system.get("requires", [])
if not any(item.startswith("setuptools>=77.0.3") for item in requires):
    fail("pyproject build-system must require setuptools>=77.0.3")
expected_project = {
    "name": "verselatch",
    "version": "1.0.0",
    "license": "GPL-3.0-only",
    "requires-python": ">=3.10",
}
for key, expected in expected_project.items():
    if project.get(key) != expected:
        fail(f"pyproject [project].{key} mismatch: {project.get(key)!r}")
if project.get("dependencies"):
    fail("PyPI runtime dependencies must not pretend to represent distro GTK/whisper.cpp/aubio dependencies")
if project.get("license-files") != ["LICENSE", "LICENSES/GPL-3.0-only.txt"]:
    fail("Python distribution license-files must describe the GPL application distribution")
if project.get("classifiers"):
    fail("public GitHub source release does not use a private/PyPI-blocking classifier")
expected_urls = {
    "Homepage": "https://github.com/erhansavas/verselatch",
    "Repository": "https://github.com/erhansavas/verselatch.git",
    "Issues": "https://github.com/erhansavas/verselatch/issues",
}
if project.get("urls") != expected_urls:
    fail(f"public project URLs mismatch: {project.get('urls')!r}")
if setuptools_cfg.get("package-dir") != {"": "src"}:
    fail("setuptools package-dir must use src layout")
if setuptools_cfg.get("py-modules") != ["verselatch"]:
    fail("setuptools must package the verselatch module")
find_cfg = setuptools_cfg.get("packages", {}).get("find", {})
if find_cfg.get("where") != ["src"] or find_cfg.get("include") != ["verselatch_core*"]:
    fail("setuptools package discovery must be restricted to src/verselatch_core")
pytest_addopts = str(pytest_cfg.get("addopts", ""))
for required_option in ("--import-mode=importlib", "--strict-config", "--strict-markers", "--disable-plugin-autoload"):
    if required_option not in pytest_addopts:
        fail(f"pytest release configuration missing: {required_option}")
dependency_groups = pyproject.get("dependency-groups", {})
for group in ("test", "lint", "security", "build", "dev"):
    if group not in dependency_groups:
        fail(f"missing PEP 735 dependency group: {group}")
if not any(str(item).startswith("pytest>=8.4") for item in dependency_groups["test"]):
    fail("pytest dependency floor must support explicit plugin-autoload disabling")
if not any(str(item).startswith("bandit>=1.9") for item in dependency_groups["security"]):
    fail("security dependency group must include Bandit")

stale_project_headers = (
    f"{SPDX_LICENSE_TAG} GPL-3.0-or-later",
    f"{SPDX_LICENSE_TAG} AGPL-3.0-only",
    f"{SPDX_LICENSE_TAG} AGPL-3.0-or-later",
)
for path in release_files:
    try:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
    except (UnicodeDecodeError, OSError):
        continue
    for stale_header in stale_project_headers:
        if stale_header in head:
            fail(f"stale first-party license header in {path.relative_to(ROOT)}: {stale_header}")

for path in release_files:
    rel = path.relative_to(ROOT).as_posix()
    if path.suffix.casefold() in FORBIDDEN_RELEASE_SUFFIXES:
        fail(f"unexpected bundled binary/model/font/media asset: {rel}")
    if path.stat().st_size > MAX_NORMAL_RELEASE_FILE and not rel.startswith("LICENSES/"):
        fail(f"unexpected large release file (>10 MiB): {rel}")

# All executable Python in this source tree must avoid import-path mutation.
python_sources = [
    *sorted(SRC.rglob("*.py")),
    *sorted((ROOT / "tests").rglob("*.py")),
    *sorted((ROOT / "tools").rglob("*.py")),
]
for path in python_sources:
    text, tree = parse_python(path)
    import_path_mutations = (
        "sys.path." + "insert",
        "sys.path." + "append",
        "sys.path." + "extend",
        "site." + "addsitedir",
    )
    if any(token in text for token in import_path_mutations):
        fail(f"import-path mutation forbidden: {path.relative_to(ROOT)}")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "sys" and target.attr == "path":
                    fail(f"sys.path assignment forbidden: {path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}")

# Runtime Python remains network-free and shell-free.
runtime_python = [APP, *sorted(CORE.glob("*.py"))]
for path in runtime_python:
    _, tree = parse_python(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_RUNTIME_MODULES:
                    fail(f"runtime network import in {path.name}: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in BANNED_RUNTIME_MODULES:
                fail(f"runtime network import in {path.name}: {node.module}")
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    fail(f"shell=True in runtime Python: {path.name}:{getattr(node, 'lineno', '?')}")

source, tree = parse_python(APP)
for required in (
    'APP_VERSION = "1.0.0"',
    f'APP_ID = "{APP_ID}"',
    MODEL_SHA,
    MODEL_SIZE,
    "native_tool_env,",
    "UNSAFE_NATIVE_ENV_KEYS",
    'label="Cancel"',
    "def cancel_analysis(",
    'label="Lyrics and timestamps reviewed"',
    'input_group = Adw.PreferencesGroup()',
    'self.status_label = Gtk.Label(label="Choose an audio file to begin")',
    'label="Verification"',
    'label="LRC Preview"',
    "Unverified draft ready",
    "not authoritative lyrics",
    "safe_write_lrc",
    "AnalysisCancelled",
    "self.analysis_run_id",
    "discarded stale analysis callback",
    "lyrics_source_state",
    "Audio changed while it was being read",
    'license_type=Gtk.License.GPL_3_0_ONLY',
    'developer_name="erhansavas"',
    '"AppStream metadata — MIT"',
    "Gtk.License.CUSTOM",
    "The AppStream metadata is licensed under the MIT License.",
    '"Follow System", "system"',
    '"Light", "light"',
    '"Dark", "dark"',
    'DEFAULT_THEME = "system"',
    'intro_title = Gtk.Label(label="Create LRC")',
    'self.set_default_size(\n            800,\n            600,\n        )',
    'Adw.ActionRow(',
    'Adw.EntryRow(title="Language")',
    'self.analyze_button = Gtk.Button(label="Generate Draft")',
    'self.analyze_button.add_css_class("pill")',
    'menu_button.set_primary(True)',
    'toolbar.set_top_bar_style(Adw.ToolbarStyle.FLAT)',
    'intro_copy.add_css_class("body")',
    'self.clear_button.add_css_class("flat")',
    'Adw.ShortcutsDialog()',
    'footer = Gtk.Label(label="GPL-3.0-only · © 2026 erhansavas")',
    'page.append(footer)',
    "Leave blank for automatic detection",
    'Gtk.Label(label="tr, en, ru")',
    'not busy and not bool(self.language_entry.get_text().strip())',
    "Analysis runs locally and can take several minutes on CPU",
    "Selected lyric words remain unchanged unless edited in the preview.",
):
    if required not in source:
        fail(f"missing application invariant: {required}")

for forbidden in (
    "CMU Serif",
    "Latin Modern Roman",
    "Generate Lyrics",
    "Download LRC",
    "media-playback-start-symbolic",
    "Adw.ButtonContent",
    "shell=True",
    "subprocess.PIPE",
    "font-size:",
    "license_type=Gtk.License.GPL_3_0,",
    "Gtk.License.MIT_X11",
    "Local processing ·",
    "Source → Analyze → Review → Save",
    "Lyrics that fit the recording.",
    "Create and Align LRC Files",
    "Legal & About",
    "theme_dropdown",
    '"Dark Gray", "gray"',
    '"Pure Black", "black"',
    "THEME_PALETTES",
    "auto-detect",
    "same-name lyrics",
    "This can take a short while on CPU",
    "unless you edit the preview",
    "background-color:",
    "--window-bg-color:",
    "--accent-bg-color:",
    "--accent-fg-color:",
    "sys.path." + "insert",
    "welcome_card",
    "content.append(footer)",
    "Audio is required; lyrics are optional",
    "Create a draft from audio or verify and align existing lyrics",
    "The MIT License applies only to",
    'Adw.PreferencesGroup(title="Source")',
    'Adw.PreferencesGroup(title="Analysis")',
    'self.status_row = Adw.ActionRow(',
    'Adw.ButtonRow(title="Generate Draft")',
    'intro_title = Gtk.Label(label="LRC Timing")',
):
    if forbidden in source:
        fail(f"forbidden/stale application token: {forbidden}")

for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("verselatch_core"):
        for alias in node.names:
            if alias.name.startswith("_"):
                fail(f"application imports private core API: {node.module}.{alias.name}")

if source.count("does not send telemetry") != 1:
    fail("privacy/telemetry statement must have one UI source of truth in About")
if source.count("background service") != 1:
    fail("background-service statement must have one UI source of truth in About")
if source.count("The AppStream metadata is licensed under the MIT License.") != 1:
    fail("MIT AppStream legal statement must be singular and explicit")
if "menu.append_section(None, appearance_section)" not in source or "menu.append_section(None, about_section)" not in source:
    fail("primary menu must separate appearance controls from the standard About item")
helper_start = source.find("    def refresh_primary_action_style(")
helper_end = source.find("    def set_analysis_action(", helper_start)
if helper_start < 0 or helper_end < 0:
    fail("primary-action semantic-style helper is missing")
helper = source[helper_start:helper_end]
for token in (
    'self.analyze_button.remove_css_class("suggested-action")',
    'self.save_button.remove_css_class("suggested-action")',
):
    if token not in helper:
        fail(f"primary-action style helper missing neutralization: {token}")
if helper.count('add_css_class("suggested-action")') != 2 or source.count('add_css_class("suggested-action")') != 2:
    fail("suggested-action styling must be centralized and mutually exclusive")

owners: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "safe_write_lrc":
                owners.append(node.name)
if [name for name in owners if name != "self_test"] != ["save_result"]:
    fail(f"unexpected safe_write_lrc callers: {owners!r}")

for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    if not (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "Popen"
    ):
        continue
    keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
    if "env" not in keywords:
        fail(f"Popen without explicit environment near line {node.lineno}")
    if not (
        isinstance(keywords.get("start_new_session"), ast.Constant)
        and keywords["start_new_session"].value is True
    ):
        fail(f"Popen without process-group isolation near line {node.lineno}")
    if "stdout" not in keywords or "stderr" not in keywords:
        fail(f"Popen without bounded-file output routing near line {node.lineno}")

for relative in (
    "packaging/linux/install-user.sh",
    "packaging/linux/install-model.sh",
    "docs/DEPENDENCIES.md",
    "docs/THIRD_PARTY_NOTICES.txt",
):
    text = read(ROOT / relative)
    compact_text = text.replace(",", "").replace("_", "")
    for value in (PINNED_REVISION, MODEL_SHA):
        if value not in text:
            fail(f"model identity mismatch/missing in {relative}: {value}")
    if MODEL_SIZE not in compact_text:
        fail(f"model size mismatch/missing in {relative}: {MODEL_SIZE}")

process_source = read(CORE / "process.py")
for token in ("def native_tool_env(", "def terminate_process_group(", "UNSAFE_NATIVE_ENV_KEYS"):
    if token not in process_source:
        fail(f"process policy missing: {token}")
for path in sorted(CORE.glob("*.py")):
    text = read(path)
    if "import gi" in text or "from gi.repository" in text:
        fail(f"GTK dependency leaked into core module: {path.name}")
    if f"{SPDX_COPYRIGHT_TAG} 2026 erhansavas" not in text or f"{SPDX_LICENSE_TAG} GPL-3.0-only" not in text:
        fail(f"missing first-party SPDX header: {path.relative_to(ROOT)}")

# Desktop/AppStream identity and public-release truthfulness.
desktop = read(ROOT / "data" / f"{APP_ID}.desktop")
for token in (
    "Type=Application", "Name=VerseLatch", "TryExec=verselatch", "Exec=verselatch",
    f"Icon={APP_ID}", "Categories=AudioVideo;Audio;",
):
    if token not in desktop:
        fail(f"desktop entry missing: {token}")
metainfo_path = ROOT / "data" / f"{APP_ID}.metainfo.xml"
meta = read(metainfo_path)
try:
    meta_root = ET.fromstring(meta)
except ET.ParseError as exc:
    fail(f"invalid AppStream XML: {exc}")
if not meta_root.tag.endswith("component"):
    fail("AppStream root is not a component")
for token in (
    f"<id>{APP_ID}</id>",
    "<metadata_license>MIT</metadata_license>",
    "<project_license>GPL-3.0-only</project_license>",
    "<summary>Create and align LRC timing</summary>",
    '<developer id="io.github.erhansavas">',
    '<release version="1.0.0" date="2026-08-12">',
    '<url type="homepage">https://github.com/erhansavas/verselatch</url>',
    '<url type="bugtracker">https://github.com/erhansavas/verselatch/issues</url>',
):
    if token not in meta:
        fail(f"public-release metainfo missing: {token}")
if 'type="development"' in meta:
    fail("public AppStream metadata must not retain the development release marker")

for icon_name in (f"{APP_ID}.svg", f"{APP_ID}-symbolic.svg"):
    icon = ROOT / "data" / icon_name
    icon_text = read(icon)
    try:
        root = ET.fromstring(icon_text)
    except ET.ParseError as exc:
        fail(f"invalid SVG {icon_name}: {exc}")
    if not root.tag.endswith("svg"):
        fail(f"icon is not SVG: {icon_name}")
    if f"{SPDX_COPYRIGHT_TAG} 2026 erhansavas" not in icon_text:
        fail(f"icon provenance header missing: {icon_name}")

for python_path in sorted(ROOT.rglob("*.py")):
    python_text = python_path.read_text(encoding="utf-8")
    if "\n\n\n\n" in python_text:
        fail(f"Python source contains an excessive blank-line run: {python_path.relative_to(ROOT)}")


# License scope: Python/application distribution is GPL-3.0-only. The AppStream
# metadata is a separately MIT-licensed file, not a second license for the app.
gpl = ROOT / "LICENSES" / "GPL-3.0-only.txt"
mit = ROOT / "LICENSES" / "MIT.txt"
license_root = ROOT / "LICENSE"
for required_file in (gpl, mit, license_root, DOCS / "PROVENANCE.md", DOCS / "LICENSING.md", ROOT / "REUSE.toml"):
    if not required_file.is_file() or required_file.is_symlink():
        fail(f"required license/provenance file missing or unsafe: {required_file.relative_to(ROOT)}")
if license_root.read_bytes() != gpl.read_bytes():
    fail("root LICENSE must be the canonical GPL-3.0-only text")
if (SPDX_LICENSE_TAG + " MIT") not in "\n".join(meta.splitlines()[:6]):
    fail("AppStream metadata must retain its explicit MIT SPDX header")
for stale_license in ("GPL-3.0-or-later.txt", "AGPL-3.0-only.txt", "AGPL-3.0-or-later.txt"):
    if (ROOT / "LICENSES" / stale_license).exists():
        fail(f"stale project license file present: {stale_license}")
for path in release_files:
    if path.suffix in {".py", ".sh", ".desktop", ".svg", ".toml"}:
        if path.name == "REUSE.toml":
            continue
        text = read(path)
        if SPDX_LICENSE_TAG not in text:
            fail(f"commentable source missing SPDX license header: {path.relative_to(ROOT)}")

release_source = read(ROOT / "tools" / "release.py")
if "os.access(" in release_source:
    fail("release mode bits still depend on ambient filesystem permissions")
for token in (
    '"src/verselatch.py"',
    '"packaging/linux/install-user.sh"',
    '"packaging/linux/install-model.sh"',
    '"packaging/linux/uninstall-user.sh"',
    '"tools/public_release_check.sh"',
):
    if token not in release_source:
        fail(f"release executable-path policy missing: {token}")

installer = read(PACKAGING / "install-user.sh")
for token in (
    'PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"',
    'SOURCE="${PROJECT_ROOT}/src/verselatch.py"',
    'CORE_SOURCE="${PROJECT_ROOT}/src/verselatch_core"',
    'UNINSTALL_SOURCE="${SCRIPT_DIR}/uninstall-user.sh"',
    'MODEL_INSTALL_SOURCE="${SCRIPT_DIR}/install-model.sh"',
    "APP_STAGE",
    "EXPECTED_SHA256",
    'hasattr(Gtk.License, "GPL_3_0_ONLY")',
    'if adw < (1, 8):',
    '"PreferencesGroup",',
    '"ActionRow",',
    '"EntryRow",',
    '"ButtonRow",',
    '"ShortcutsDialog",',
    "DESKTOP_EXEC_FORBIDDEN_CHARS",
    'python3 -E -s -B "${APP_STAGE}/verselatch.py" --self-test',
    'python3 -E -s -B "${APP_STAGE}/verselatch.py" --smoke-test',
    'python3 -E -s -B "\\${APP}" "\\$@"',
    'export PATH=\\"\\$HOME/.local/bin:\\$PATH\\"',
):
    if token not in installer:
        fail(f"installer missing release invariant: {token}")
if "shellcheck disable=" in installer:
    fail("installer must not suppress ShellCheck diagnostics")
launcher = read(PACKAGING / "verselatch")
if '/usr/lib/verselatch/verselatch.py' not in launcher:
    fail("system launcher points to an unexpected app path")
if 'python3 -E -s -B "${APP}"' not in launcher:
    fail("system launcher must ignore PYTHON* env and user site without sys.path mutation")
if "python3 -I -B \"${APP}\"" in launcher:
    fail("system launcher still requires isolated-mode path bootstrap")

quality_gate = read(ROOT / "tools" / "quality_gate.sh")
for token in (
    "export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    "public_metadata=1",
    "need bandit",
    "bandit -q -r src tools -x tests -ll",
    "Bandit medium/high-severity security scan: PASS",
    "python3 -m venv --without-pip --system-site-packages",
    'python3 -m pip --python "${qa_editable}" install',
    'python3 -m pip --python "${qa_wheel_venv}" install',
    "QUALITY GATE FAILED near line",
):
    if token not in quality_gate:
        fail(f"quality gate missing security/determinism invariant: {token}")
for forbidden in (
    "MISSING OPTIONAL QUALITY TOOL: bandit",
    "Bandit advisory scan",
    "--exit-zero",
    "pip check",
):
    if forbidden in quality_gate:
        fail(f"quality gate contains fail-open security scanner behavior: {forbidden}")

secret_markers = (
    "-----BEGIN " + "PRIVATE KEY-----",
    "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
    "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----",
)
for path in release_files:
    if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if any(marker in text for marker in secret_markers):
        fail(f"private-key material marker found: {path.relative_to(ROOT)}")

print(f"Static tree policy: PASS ({len(release_files)} regular files)")
print("src/verselatch.py SHA-256:", hashlib.sha256(APP.read_bytes()).hexdigest())
