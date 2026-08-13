# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_LAYER = ROOT / "src" / "verselatch_app"
FORBIDDEN_PLATFORM_MODULES = {
    "ctypes",
    "gi",
    "os",
    "pathlib",
    "signal",
    "subprocess",
    "winreg",
}


def test_application_layer_has_no_platform_runtime_imports() -> None:
    violations: list[str] = []
    for path in sorted(APP_LAYER.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                root = module.split(".", 1)[0]
                if root in FORBIDDEN_PLATFORM_MODULES:
                    violations.append(f"{path.name}:{node.lineno}:{module}")
    assert not violations, violations
