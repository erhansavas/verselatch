# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "stage_linux_worker_bundle.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("stage_linux_worker_bundle", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def elf(machine: int) -> bytes:
    ident = b"\x7fELF" + bytes((2, 1, 1, 0, 0)) + b"\x00" * 7
    return ident + (2).to_bytes(2, "little") + machine.to_bytes(2, "little") + b"\x01\x00\x00\x00"


def test_worker_bundle_architecture_aliases_are_explicit() -> None:
    tool = load_tool()
    assert tool.normalize_architecture("x86_64") == "x86_64"
    assert tool.normalize_architecture("amd64") == "x86_64"
    assert tool.normalize_architecture("aarch64") == "aarch64"
    assert tool.normalize_architecture("arm64") == "aarch64"
    with pytest.raises(tool.BundleError):
        tool.normalize_architecture("i686")


def test_worker_bundle_reads_exact_elf_machine_identity() -> None:
    tool = load_tool()
    assert tool.inspect_elf(elf(62)) == "x86_64"
    assert tool.inspect_elf(elf(183)) == "aarch64"
    with pytest.raises(tool.BundleError):
        tool.inspect_elf(b"not-elf")
    with pytest.raises(tool.BundleError):
        tool.inspect_elf(elf(3))


def test_worker_bundle_rejects_symlink_input(tmp_path: Path) -> None:
    tool = load_tool()
    real = tmp_path / "real-worker"
    real.write_bytes(elf(62))
    real.chmod(0o755)
    link = tmp_path / "worker"
    link.symlink_to(real)
    with pytest.raises(tool.BundleError):
        tool.read_worker(link, "x86_64")


def test_worker_bundle_roundtrip_has_exact_inventory_and_provenance(tmp_path: Path) -> None:
    tool = load_tool()
    worker = tmp_path / "worker"
    worker.write_bytes(elf(62) + b"fixture-worker")
    worker.chmod(0o755)
    context = tool.SourceContext(
        "1" * 40,
        "2" * 64,
        tool.WHISPER_GIT_COMMIT,
        tool.YYJSON_GIT_COMMIT,
    )
    bundle = tmp_path / "bundle"
    tool.stage_from_context(worker, bundle, "amd64", context)
    document = tool.verify_from_context(bundle, context)

    inventory = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file()
    }
    assert inventory == tool.BUNDLE_FILES
    assert document["target"] == {"architecture": "x86_64", "os": "linux"}
    assert document["worker"]["path"] == "app/bin/verselatch-worker"
    assert document["worker"]["mode"] == "0755"
    assert (bundle / "app/bin/verselatch-worker").stat().st_mode & 0o777 == 0o755

    with pytest.raises(tool.BundleError):
        tool.stage_from_context(worker, bundle, "x86_64", context)


def test_worker_bundle_verification_rejects_tampering(tmp_path: Path) -> None:
    tool = load_tool()
    worker = tmp_path / "worker"
    worker.write_bytes(elf(183) + b"fixture-worker")
    worker.chmod(0o755)
    context = tool.SourceContext(
        "3" * 40,
        "4" * 64,
        tool.WHISPER_GIT_COMMIT,
        tool.YYJSON_GIT_COMMIT,
    )
    bundle = tmp_path / "bundle"
    tool.stage_from_context(worker, bundle, "arm64", context)
    staged = bundle / "app/bin/verselatch-worker"
    staged.write_bytes(staged.read_bytes() + b"tamper")
    with pytest.raises(tool.BundleError):
        tool.verify_from_context(bundle, context)


def test_source_and_ci_policy_keep_prebuilt_worker_out_of_git() -> None:
    manifest = (ROOT / "SHA256SUMS").read_text(encoding="utf-8")
    paths = [line.partition("  ")[2] for line in manifest.splitlines() if line]
    assert not any(Path(path).name == "verselatch-worker" for path in paths)

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "stage_linux_worker_bundle.py stage" in workflow
    assert "stage_linux_worker_bundle.py verify" in workflow
    assert '--source-commit "$GITHUB_SHA"' in workflow
