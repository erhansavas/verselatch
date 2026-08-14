#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

import stage_linux_worker_bundle as worker_bundle

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_SCHEMA = 1
PROVENANCE_REL = "metadata/app-payload-provenance.json"
MANIFEST_REL = "SHA256SUMS"
APP_ROOT_REL = "app"
SOURCE_ENTRYPOINT = "src/verselatch.py"
SOURCE_PACKAGE_DIRS = (
    "src/verselatch_core",
    "src/verselatch_app",
    "src/verselatch_platform",
)


class PayloadError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_exact(path: Path, expected_sha256: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise PayloadError(f"cannot safely open source payload file: {path}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise PayloadError(f"source payload member is not a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise PayloadError(f"source payload member changed while being read: {path}")
    finally:
        os.close(fd)

    data = b"".join(chunks)
    if len(data) != before.st_size or _sha256(data) != expected_sha256:
        raise PayloadError(f"source payload member does not match source manifest: {path}")
    return data


def source_app_inventory(root: Path, source_hashes: dict[str, str]) -> tuple[str, ...]:
    paths: list[str] = []
    if SOURCE_ENTRYPOINT not in source_hashes:
        raise PayloadError("source manifest does not contain src/verselatch.py")
    paths.append(SOURCE_ENTRYPOINT)

    for rel_dir in SOURCE_PACKAGE_DIRS:
        directory = root / rel_dir
        if not directory.is_dir() or directory.is_symlink():
            raise PayloadError(f"source package directory is missing or unsafe: {rel_dir}")
        prefix = rel_dir + "/"
        all_package_members = sorted(
            rel for rel in source_hashes if rel.startswith(prefix)
        )
        if any(Path(rel).parent.as_posix() != rel_dir for rel in all_package_members):
            raise PayloadError(f"nested source package members are not supported: {rel_dir}")
        package_files = all_package_members
        if not package_files or f"{rel_dir}/__init__.py" not in package_files:
            raise PayloadError(f"source package inventory is incomplete: {rel_dir}")
        if any(Path(rel).suffix != ".py" for rel in package_files):
            raise PayloadError(f"source package contains a non-Python managed member: {rel_dir}")
        paths.extend(package_files)

    return tuple(paths)


def staged_rel_for_source(source_rel: str) -> str:
    if source_rel == SOURCE_ENTRYPOINT:
        return "app/verselatch.py"
    if not source_rel.startswith("src/"):
        raise PayloadError(f"unexpected source payload path: {source_rel}")
    return "app/" + source_rel[len("src/"):]


def _write_file(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, mode)


def _expected_inventory(root: Path, source_hashes: dict[str, str]) -> set[str]:
    return {
        *(staged_rel_for_source(rel) for rel in source_app_inventory(root, source_hashes)),
        "app/bin/verselatch-worker",
        PROVENANCE_REL,
        MANIFEST_REL,
    }


def _provenance(
    context: worker_bundle.SourceContext,
    *,
    architecture: str,
    worker_sha256: str,
    worker_size: int,
    app_files: tuple[str, ...],
) -> bytes:
    document = {
        "schema": PAYLOAD_SCHEMA,
        "source": {
            "commit": context.source_commit,
            "sha256sums_sha256": context.source_manifest_sha256,
            "whisper_git_commit": context.whisper_git_commit,
            "yyjson_git_commit": context.yyjson_git_commit,
        },
        "target": {
            "os": "linux",
            "architecture": architecture,
        },
        "app": {
            "root": APP_ROOT_REL,
            "files": list(app_files),
        },
        "worker": {
            "path": "app/bin/verselatch-worker",
            "sha256": worker_sha256,
            "size": worker_size,
            "mode": "0755",
        },
    }
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_manifest(root: Path, paths: set[str]) -> None:
    manifest_members = sorted(paths - {MANIFEST_REL})
    lines = [
        f"{_sha256((root / rel).read_bytes())}  {rel}\n"
        for rel in manifest_members
    ]
    _write_file(root / MANIFEST_REL, "".join(lines).encode("utf-8"), 0o644)


def _inventory(root: Path) -> set[str]:
    inventory: set[str] = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise PayloadError(f"payload bundle contains a symbolic link: {rel}")
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise PayloadError(f"payload bundle member is not a regular file: {rel}")
            inventory.add(rel)
    return inventory


def stage_from_context(
    *,
    root: Path,
    worker_bundle_path: Path,
    output: Path,
    context: worker_bundle.SourceContext,
    source_hashes: dict[str, str],
) -> None:
    root = root.resolve()
    output = output.resolve()
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise PayloadError("payload output parent must be an existing real directory")
    if os.path.lexists(output):
        raise PayloadError("payload output already exists")

    source_files = source_app_inventory(root, source_hashes)
    worker_document = worker_bundle.verify_from_context(worker_bundle_path, context)
    architecture = worker_bundle.normalize_architecture(
        str(worker_document["target"]["architecture"])
    )
    worker_info = worker_document["worker"]
    assert isinstance(worker_info, dict)
    worker_path = worker_bundle_path / worker_bundle.WORKER_REL
    worker = worker_bundle.read_worker(worker_path, architecture)
    if (
        worker.sha256 != worker_info.get("sha256")
        or worker.size != worker_info.get("size")
    ):
        raise PayloadError("verified worker bytes do not match worker-bundle provenance")

    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        app_files: list[str] = []
        for source_rel in source_files:
            staged_rel = staged_rel_for_source(source_rel)
            destination = temporary / staged_rel
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            data = _read_regular_exact(root / source_rel, source_hashes[source_rel])
            mode = 0o755 if source_rel == SOURCE_ENTRYPOINT else 0o644
            _write_file(destination, data, mode)
            app_files.append(staged_rel)

        worker_destination = temporary / "app/bin/verselatch-worker"
        worker_destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        _write_file(worker_destination, worker.data, 0o755)
        app_files.append("app/bin/verselatch-worker")

        metadata_dir = temporary / "metadata"
        metadata_dir.mkdir(mode=0o755)
        _write_file(
            temporary / PROVENANCE_REL,
            _provenance(
                context,
                architecture=architecture,
                worker_sha256=worker.sha256,
                worker_size=worker.size,
                app_files=tuple(sorted(app_files)),
            ),
            0o644,
        )

        expected = _expected_inventory(root, source_hashes)
        _write_manifest(temporary, expected)
        verify_from_context(
            root=root,
            bundle=temporary,
            context=context,
            source_hashes=source_hashes,
        )
        if os.path.lexists(output):
            raise PayloadError("payload output appeared during staging")
        os.rename(temporary, output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def verify_from_context(
    *,
    root: Path,
    bundle: Path,
    context: worker_bundle.SourceContext,
    source_hashes: dict[str, str],
) -> dict[str, object]:
    root = root.resolve()
    bundle = bundle.resolve()
    if not bundle.is_dir() or bundle.is_symlink():
        raise PayloadError("payload bundle is missing or unsafe")

    expected = _expected_inventory(root, source_hashes)
    actual = _inventory(bundle)
    if actual != expected:
        raise PayloadError(
            f"payload bundle inventory mismatch; missing={sorted(expected-actual)!r} "
            f"extra={sorted(actual-expected)!r}"
        )

    manifest: dict[str, str] = {}
    for line in (bundle / MANIFEST_REL).read_text(encoding="utf-8").splitlines():
        digest, sep, rel = line.partition("  ")
        if (
            not sep
            or rel not in expected - {MANIFEST_REL}
            or rel in manifest
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise PayloadError(f"invalid payload manifest line: {line!r}")
        manifest[rel] = digest
    if set(manifest) != expected - {MANIFEST_REL}:
        raise PayloadError("payload manifest inventory is incomplete")
    for rel, digest in manifest.items():
        if _sha256((bundle / rel).read_bytes()) != digest:
            raise PayloadError(f"payload manifest hash mismatch: {rel}")

    try:
        document = json.loads((bundle / PROVENANCE_REL).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadError("payload provenance is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict) or set(document) != {
        "app", "schema", "source", "target", "worker"
    }:
        raise PayloadError("payload provenance top-level schema is invalid")
    if document["schema"] != PAYLOAD_SCHEMA:
        raise PayloadError("payload provenance schema version is invalid")

    expected_source = {
        "commit": context.source_commit,
        "sha256sums_sha256": context.source_manifest_sha256,
        "whisper_git_commit": context.whisper_git_commit,
        "yyjson_git_commit": context.yyjson_git_commit,
    }
    if document["source"] != expected_source:
        raise PayloadError("payload provenance source identity mismatch")

    target = document["target"]
    if not isinstance(target, dict) or set(target) != {"architecture", "os"}:
        raise PayloadError("payload provenance target schema is invalid")
    if target["os"] != "linux":
        raise PayloadError("payload target OS is not Linux")
    architecture = worker_bundle.normalize_architecture(str(target["architecture"]))

    expected_app_files = sorted(expected - {MANIFEST_REL, PROVENANCE_REL})
    app = document["app"]
    if (
        not isinstance(app, dict)
        or set(app) != {"files", "root"}
        or app["root"] != APP_ROOT_REL
        or app["files"] != expected_app_files
    ):
        raise PayloadError("payload provenance app inventory mismatch")

    worker_info = document["worker"]
    if (
        not isinstance(worker_info, dict)
        or set(worker_info) != {"mode", "path", "sha256", "size"}
        or worker_info["path"] != "app/bin/verselatch-worker"
        or worker_info["mode"] != "0755"
    ):
        raise PayloadError("payload worker provenance schema is invalid")
    staged_worker = bundle / "app/bin/verselatch-worker"
    if stat.S_IMODE(staged_worker.stat().st_mode) != 0o755:
        raise PayloadError("payload worker mode is not exactly 0755")
    worker_data = staged_worker.read_bytes()
    if (
        worker_info["sha256"] != _sha256(worker_data)
        or worker_info["size"] != len(worker_data)
        or worker_bundle.inspect_elf(worker_data) != architecture
    ):
        raise PayloadError("payload worker provenance mismatch")

    source_files = source_app_inventory(root, source_hashes)
    for source_rel in source_files:
        staged_rel = staged_rel_for_source(source_rel)
        expected_data = _read_regular_exact(root / source_rel, source_hashes[source_rel])
        staged = bundle / staged_rel
        expected_mode = 0o755 if source_rel == SOURCE_ENTRYPOINT else 0o644
        if staged.read_bytes() != expected_data:
            raise PayloadError(f"staged application source mismatch: {staged_rel}")
        if stat.S_IMODE(staged.stat().st_mode) != expected_mode:
            raise PayloadError(f"staged application mode mismatch: {staged_rel}")

    return document


def _assert_outside_source(path: Path, root: Path) -> None:
    resolved = path.resolve()
    source = root.resolve()
    if resolved == source or source in resolved.parents:
        raise PayloadError("payload output must remain outside the Git source tree")


def source_snapshot(
    root: Path,
    source_commit: str | None,
) -> tuple[worker_bundle.SourceContext, dict[str, str]]:
    context = worker_bundle.source_context(root, source_commit)
    _order, mapping, _raw = worker_bundle.parse_manifest(root)
    return context, mapping


def stage_payload(
    *,
    worker_bundle_path: Path,
    output: Path,
    source_commit: str | None,
    root: Path = ROOT,
) -> None:
    _assert_outside_source(output, root)
    context, source_hashes = source_snapshot(root, source_commit)
    stage_from_context(
        root=root,
        worker_bundle_path=worker_bundle_path,
        output=output,
        context=context,
        source_hashes=source_hashes,
    )


def verify_payload(
    *,
    bundle: Path,
    source_commit: str | None,
    root: Path = ROOT,
) -> dict[str, object]:
    _assert_outside_source(bundle, root)
    context, source_hashes = source_snapshot(root, source_commit)
    return verify_from_context(
        root=root,
        bundle=bundle,
        context=context,
        source_hashes=source_hashes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage and verify a complete Linux VerseLatch application payload."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage")
    stage.add_argument("--worker-bundle", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)
    stage.add_argument("--source-commit")

    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--source-commit")

    args = parser.parse_args()
    if args.command == "stage":
        stage_payload(
            worker_bundle_path=args.worker_bundle,
            output=args.output,
            source_commit=args.source_commit,
        )
        document = verify_payload(
            bundle=args.output,
            source_commit=args.source_commit,
        )
        print(
            "LINUX APP PAYLOAD STAGE: PASS "
            f"arch={document['target']['architecture']} "
            f"files={len(document['app']['files'])}"
        )
    else:
        document = verify_payload(
            bundle=args.bundle,
            source_commit=args.source_commit,
        )
        print(
            "LINUX APP PAYLOAD VERIFY: PASS "
            f"arch={document['target']['architecture']} "
            f"files={len(document['app']['files'])}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PayloadError, worker_bundle.BundleError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
