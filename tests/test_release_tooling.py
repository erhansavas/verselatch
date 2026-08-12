# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verselatch_release", ROOT / "tools" / "release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_release_modes_are_source_controlled_not_ambient_permissions(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    app = src / "verselatch.py"
    readme = tmp_path / "README.md"
    app.write_text("print('ok')\n", encoding="utf-8")
    readme.write_text("readme\n", encoding="utf-8")

    app.chmod(0o600)
    readme.chmod(0o755)
    assert release.normalized_mode(tmp_path, app) == 0o755
    assert release.normalized_mode(tmp_path, readme) == 0o644


def test_zip_bytes_remain_identical_when_host_mode_bits_change(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    src = root / "src"
    src.mkdir()
    app = src / "verselatch.py"
    readme = root / "README.md"
    app.write_text("print('ok')\n", encoding="utf-8")
    readme.write_text("readme\n", encoding="utf-8")
    a = tmp_path / "a.zip"
    b = tmp_path / "b.zip"

    app.chmod(0o600)
    readme.chmod(0o755)
    release.build_zip(root, a, "VerseLatch-1.0.0", 1_786_500_000)

    app.chmod(0o777)
    readme.chmod(0o600)
    release.build_zip(root, b, "VerseLatch-1.0.0", 1_786_500_000)

    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as archive:
        app_info = archive.getinfo("VerseLatch-1.0.0/src/verselatch.py")
        readme_info = archive.getinfo("VerseLatch-1.0.0/README.md")
    assert (app_info.external_attr >> 16) & 0o777 == 0o755
    assert (readme_info.external_attr >> 16) & 0o777 == 0o644


def test_release_builder_rejects_symlinks_and_special_files(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    target = root / "real.txt"
    target.write_text("ok\n", encoding="utf-8")
    (root / "link.txt").symlink_to(target)
    with pytest.raises(SystemExit, match="symlink"):
        list(release.iter_paths(root))

    (root / "link.txt").unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "fifo")
        with pytest.raises(SystemExit, match="special file"):
            list(release.iter_paths(root))
