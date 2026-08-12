# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP = SRC / "verselatch.py"
CORE = SRC / "verselatch_core"


def test_runtime_python_has_no_network_import_or_shell_true():
    banned = {"aiohttp", "ftplib", "http", "requests", "smtplib", "socket", "urllib", "websockets"}
    for path in [APP, *sorted(CORE.glob("*.py"))]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in banned for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant):
                        assert keyword.value.value is not True


def test_core_package_is_gtk_independent():
    for path in sorted(CORE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "import gi" not in text
        assert "from gi.repository" not in text


def test_main_module_does_not_depend_on_private_alignment_helpers():
    text = APP.read_text(encoding="utf-8")
    assert "_map_lyrics_to_segments" not in text
    assert "_timed_words_for_segments" not in text
