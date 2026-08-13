# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SHA256SUMS"
IGNORED_PARTS = {
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "__pycache__", "build", "dist",
}


def release_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.is_symlink() or path == MANIFEST:
            continue
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        files[relative.as_posix()] = path
    return files


def parse_manifest() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        assert separator and len(digest) == 64 and name, line
        assert name not in entries, name
        entries[name] = digest
    return entries


def test_source_manifest_matches_release_tree() -> None:
    manifest = parse_manifest()
    actual = release_files()
    problems: list[str] = []
    for name in sorted(set(manifest) - set(actual)):
        problems.append(f"missing: {name}")
    for name in sorted(set(actual) - set(manifest)):
        digest = hashlib.sha256(actual[name].read_bytes()).hexdigest()
        problems.append(f"unlisted: {digest}  {name}")
    for name in sorted(set(manifest) & set(actual)):
        digest = hashlib.sha256(actual[name].read_bytes()).hexdigest()
        if digest != manifest[name]:
            problems.append(f"mismatch: {digest}  {name}")
    assert not problems, "\n" + "\n".join(problems)
