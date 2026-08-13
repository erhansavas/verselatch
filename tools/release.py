#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import os
from pathlib import Path
import stat
import tarfile
import zipfile

EXCLUDE_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "build", "dist"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


EXECUTABLE_PATHS = frozenset({
    "src/verselatch.py",
    "packaging/linux/install-user.sh",
    "packaging/linux/install-model.sh",
    "packaging/linux/uninstall-user.sh",
    "packaging/linux/verselatch",
    "tools/native_release_check.sh",
    "tools/public_release_check.sh",
    "tools/quality_gate.sh",
    "tools/release.py",
    "tools/validate_appstream.sh",
    "tools/verify_tree.py",
})


def iter_paths(root: Path):
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        rel = path.relative_to(root)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise SystemExit(f"release tree contains symlink: {rel}")
        if stat.S_ISREG(mode):
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
        elif not stat.S_ISDIR(mode):
            raise SystemExit(f"release tree contains special file: {rel}")
        yield path, rel


def normalized_mode(root: Path, path: Path) -> int:
    if path.is_dir():
        return 0o755
    relative = path.relative_to(root).as_posix()
    return 0o755 if relative in EXECUTABLE_PATHS else 0o644


def zip_time(epoch: int):
    value = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
    if value.year < 1980:
        value = dt.datetime(1980, 1, 1, tzinfo=dt.timezone.utc)
    return (value.year, value.month, value.day, value.hour, value.minute, value.second - value.second % 2)


def build_zip(root: Path, output: Path, prefix: str, epoch: int) -> None:
    timestamp = zip_time(epoch)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, rel in iter_paths(root):
            if path.is_dir():
                continue
            name = f"{prefix}/{rel.as_posix()}"
            info = zipfile.ZipInfo(name, timestamp)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((stat.S_IFREG | normalized_mode(root, path)) & 0xFFFF) << 16
            info.extra = b""
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_tar(root: Path, output: Path, prefix: str, epoch: int) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tf:
        root_info = tarfile.TarInfo(prefix + "/")
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        root_info.uid = root_info.gid = 0
        root_info.uname = root_info.gname = ""
        root_info.mtime = epoch
        tf.addfile(root_info)
        for path, rel in iter_paths(root):
            name = f"{prefix}/{rel.as_posix()}"
            info = tarfile.TarInfo(name + ("/" if path.is_dir() else ""))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = epoch
            info.mode = normalized_mode(root, path)
            if path.is_dir():
                info.type = tarfile.DIRTYPE
                tf.addfile(info)
            else:
                data = path.read_bytes()
                info.size = len(data)
                info.type = tarfile.REGTYPE
                tf.addfile(info, io.BytesIO(data))
    with output.open("wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=epoch) as gz:
            gz.write(raw.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--label", default="VerseLatch-1.0.1")
    parser.add_argument("--zip-name", default="VerseLatch-1.0.1.zip")
    parser.add_argument("--tar-name", default="VerseLatch-1.0.1.tar.gz")
    args = parser.parse_args()
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if not raw_epoch or not raw_epoch.isdecimal():
        raise SystemExit("SOURCE_DATE_EPOCH must be an integer for deterministic artifacts")
    epoch = int(raw_epoch)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    build_zip(args.root.resolve(), args.out_dir / args.zip_name, args.label, epoch)
    build_tar(args.root.resolve(), args.out_dir / args.tar_name, args.label, epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
