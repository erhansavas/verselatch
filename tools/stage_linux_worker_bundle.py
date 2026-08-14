#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WHISPER_GIT_COMMIT = "23ee03506a91ac3d3f0071b40e66a430eebdfa1d"
YYJSON_GIT_COMMIT = "8b4a38dc994a110abaec8a400615567bd996105f"
WORKER_REL = "app/bin/verselatch-worker"
PROVENANCE_REL = "metadata/worker-provenance.json"
MANIFEST_REL = "SHA256SUMS"
BUNDLE_FILES = {WORKER_REL, PROVENANCE_REL, MANIFEST_REL}
TRANSIENT_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv", "build", "dist"}


class BundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceContext:
    source_commit: str
    source_manifest_sha256: str
    whisper_git_commit: str
    yyjson_git_commit: str


@dataclass(frozen=True)
class WorkerArtifact:
    data: bytes
    sha256: str
    size: int
    architecture: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    p = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise BundleError(p.stderr.decode(errors="replace"))
    return p


def git_head(root: Path) -> str | None:
    p = git(root, "rev-parse", "--is-inside-work-tree", check=False)
    if p.returncode or p.stdout.strip() != b"true":
        return None
    return git(root, "rev-parse", "HEAD").stdout.decode().strip()


def parse_manifest(root: Path):
    path = root / "SHA256SUMS"
    if not path.is_file() or path.is_symlink():
        raise BundleError("source SHA256SUMS is missing or unsafe")
    raw = path.read_bytes()
    order, mapping = [], {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if not line:
            continue
        digest, sep, rel = line.partition("  ")
        if (not sep or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                or not rel or rel.startswith("/") or ".." in Path(rel).parts or rel in mapping):
            raise BundleError(f"invalid source manifest line: {line!r}")
        order.append(rel)
        mapping[rel] = digest
    return order, mapping, raw


def verify_pins(root: Path) -> None:
    text = (root / "native/worker/CMakeLists.txt").read_text(encoding="utf-8")
    for dependency, commit in (("whisper", WHISPER_GIT_COMMIT), ("yyjson", YYJSON_GIT_COMMIT)):
        marker = f"FetchContent_Declare(\n    {dependency}\n"
        start = text.find(marker)
        if start < 0 or text.find(marker, start + 1) >= 0:
            raise BundleError(f"cannot uniquely locate {dependency} FetchContent declaration")
        end = text.find("\n)", start)
        block = text[start:end]
        tags = [line.strip() for line in block.splitlines() if line.strip().startswith("GIT_TAG ")]
        if tags != [f"GIT_TAG {commit}"]:
            raise BundleError(f"{dependency} source pin is not exact")


def source_inventory(root: Path) -> set[str]:
    head = git_head(root)
    if head is not None:
        if git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout:
            raise BundleError("source git worktree is not clean")
        return {x.decode() for x in git(root, "ls-files", "-z").stdout.split(b"\0") if x}
    actual = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in TRANSIENT_DIRS for part in rel.parts):
            continue
        if path.is_symlink():
            raise BundleError(f"source tree symlink: {rel}")
        if path.is_file():
            actual.add(rel.as_posix())
    return actual


def source_context(root: Path, requested_commit: str | None) -> SourceContext:
    root = root.resolve()
    order, mapping, manifest_raw = parse_manifest(root)
    expected = set(order) | {"SHA256SUMS"}
    actual = source_inventory(root)
    if actual != expected:
        raise BundleError(f"source inventory mismatch; missing={sorted(expected-actual)!r} extra={sorted(actual-expected)!r}")
    for rel in order:
        path = root / rel
        if not path.is_file() or path.is_symlink() or sha256(path.read_bytes()) != mapping[rel]:
            raise BundleError(f"source manifest mismatch: {rel}")
    if any(Path(rel).name == "verselatch-worker" for rel in expected):
        raise BundleError("prebuilt verselatch-worker exists in source inventory")
    verify_pins(root)

    head = git_head(root)
    if requested_commit is None:
        if head is None:
            raise BundleError("--source-commit is required for an archive source tree")
        commit = head
    else:
        commit = requested_commit.lower()
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise BundleError("--source-commit must be exact 40-hex")
        if head is not None and commit != head:
            raise BundleError(f"source commit {commit} != HEAD {head}")
    return SourceContext(commit, sha256(manifest_raw), WHISPER_GIT_COMMIT, YYJSON_GIT_COMMIT)


def normalize_architecture(value: str) -> str:
    aliases = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
    try:
        return aliases[value.strip().lower()]
    except KeyError as exc:
        raise BundleError(f"unsupported Linux worker architecture: {value!r}") from exc


def inspect_elf(data: bytes) -> str:
    if len(data) < 20 or data[:4] != b"\x7fELF":
        raise BundleError("worker is not ELF")
    if data[4:7] != bytes((2, 1, 1)):
        raise BundleError("worker ELF must be 64-bit little-endian version 1")
    elf_type = int.from_bytes(data[16:18], "little")
    machine = int.from_bytes(data[18:20], "little")
    if elf_type not in {2, 3}:
        raise BundleError(f"worker ELF type is not executable: {elf_type}")
    machines = {62: "x86_64", 183: "aarch64"}
    if machine not in machines:
        raise BundleError(f"unsupported worker ELF machine: {machine}")
    return machines[machine]


def read_worker(path: Path, expected_architecture: str) -> WorkerArtifact:
    expected = normalize_architecture(expected_architecture)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BundleError(f"cannot safely open worker: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111 or before.st_mode & 0o6000:
            raise BundleError("worker must be executable regular file without setuid/setgid")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        a = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        b = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if a != b:
            raise BundleError("worker changed while being read")
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != before.st_size:
        raise BundleError("worker size mismatch")
    arch = inspect_elf(data)
    if arch != expected:
        raise BundleError(f"worker architecture {arch} != requested {expected}")
    return WorkerArtifact(data, sha256(data), len(data), arch)


def write_file(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, mode)


def provenance(context: SourceContext, worker: WorkerArtifact) -> bytes:
    doc = {
        "schema": 1,
        "source": {
            "commit": context.source_commit,
            "sha256sums_sha256": context.source_manifest_sha256,
            "whisper_git_commit": context.whisper_git_commit,
            "yyjson_git_commit": context.yyjson_git_commit,
        },
        "target": {"architecture": worker.architecture, "os": "linux"},
        "worker": {"mode": "0755", "path": WORKER_REL, "sha256": worker.sha256, "size": worker.size},
    }
    return (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode()


def stage_from_context(worker_path: Path, output: Path, architecture: str, context: SourceContext) -> None:
    output = output.resolve()
    if not output.parent.is_dir() or output.parent.is_symlink() or os.path.lexists(output):
        raise BundleError("bundle output parent must exist and output must not exist")
    worker = read_worker(worker_path, architecture)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        (temp / "app/bin").mkdir(parents=True, mode=0o755)
        (temp / "metadata").mkdir(mode=0o755)
        write_file(temp / WORKER_REL, worker.data, 0o755)
        write_file(temp / PROVENANCE_REL, provenance(context, worker), 0o644)
        lines = "".join(f"{sha256((temp/rel).read_bytes())}  {rel}\n" for rel in (WORKER_REL, PROVENANCE_REL))
        write_file(temp / MANIFEST_REL, lines.encode(), 0o644)
        verify_from_context(temp, context)
        if os.path.lexists(output):
            raise BundleError("bundle output appeared during staging")
        os.rename(temp, output)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def verify_from_context(bundle: Path, context: SourceContext) -> dict:
    bundle = bundle.resolve()
    if not bundle.is_dir() or bundle.is_symlink():
        raise BundleError("bundle is missing or unsafe")
    inventory = set()
    for path in bundle.rglob("*"):
        rel = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            raise BundleError(f"bundle symlink: {rel}")
        if path.is_file():
            inventory.add(rel)
    if inventory != BUNDLE_FILES:
        raise BundleError(f"bundle inventory mismatch: {sorted(inventory)!r}")

    mapping = {}
    for line in (bundle / MANIFEST_REL).read_text(encoding="utf-8").splitlines():
        digest, sep, rel = line.partition("  ")
        if not sep or rel not in {WORKER_REL, PROVENANCE_REL} or rel in mapping:
            raise BundleError("invalid bundle manifest")
        mapping[rel] = digest
    if set(mapping) != {WORKER_REL, PROVENANCE_REL}:
        raise BundleError("incomplete bundle manifest")
    for rel, digest in mapping.items():
        if len(digest) != 64 or sha256((bundle / rel).read_bytes()) != digest:
            raise BundleError(f"bundle manifest mismatch: {rel}")

    doc = json.loads((bundle / PROVENANCE_REL).read_text(encoding="utf-8"))
    expected_source = {
        "commit": context.source_commit,
        "sha256sums_sha256": context.source_manifest_sha256,
        "whisper_git_commit": context.whisper_git_commit,
        "yyjson_git_commit": context.yyjson_git_commit,
    }
    if set(doc) != {"schema", "source", "target", "worker"} or doc["schema"] != 1 or doc["source"] != expected_source:
        raise BundleError("worker provenance source/schema mismatch")
    if doc["target"].get("os") != "linux" or set(doc["target"]) != {"architecture", "os"}:
        raise BundleError("worker provenance target mismatch")
    arch = normalize_architecture(str(doc["target"]["architecture"]))
    info = doc["worker"]
    if set(info) != {"mode", "path", "sha256", "size"} or info["path"] != WORKER_REL or info["mode"] != "0755":
        raise BundleError("worker provenance record mismatch")
    worker_path = bundle / WORKER_REL
    if stat.S_IMODE(worker_path.stat().st_mode) != 0o755:
        raise BundleError("staged worker mode is not 0755")
    data = worker_path.read_bytes()
    if info["size"] != len(data) or info["sha256"] != sha256(data) or inspect_elf(data) != arch:
        raise BundleError("staged worker provenance mismatch")
    return doc


def assert_outside_source(path: Path, root: Path) -> None:
    resolved, source = path.resolve(), root.resolve()
    if resolved == source or source in resolved.parents:
        raise BundleError("bundle output must remain outside Git source tree")


def stage_bundle(worker: Path, output: Path, arch: str, source_commit: str | None, root: Path = ROOT) -> None:
    assert_outside_source(output, root)
    stage_from_context(worker, output, arch, source_context(root, source_commit))


def verify_bundle(bundle: Path, source_commit: str | None, root: Path = ROOT) -> dict:
    assert_outside_source(bundle, root)
    return verify_from_context(bundle, source_context(root, source_commit))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("stage")
    p.add_argument("--worker", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--arch", required=True)
    p.add_argument("--source-commit")
    v = sub.add_parser("verify")
    v.add_argument("--bundle", type=Path, required=True)
    v.add_argument("--source-commit")
    args = parser.parse_args()

    if args.command == "stage":
        stage_bundle(args.worker, args.output, args.arch, args.source_commit)
        doc = verify_bundle(args.output, args.source_commit)
        print(f"LINUX WORKER BUNDLE STAGE: PASS arch={doc['target']['architecture']} sha256={doc['worker']['sha256']}")
    else:
        doc = verify_bundle(args.bundle, args.source_commit)
        print(f"LINUX WORKER BUNDLE VERIFY: PASS arch={doc['target']['architecture']} sha256={doc['worker']['sha256']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BundleError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
