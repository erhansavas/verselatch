# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
WORKER_TOOL_PATH = TOOLS / "stage_linux_worker_bundle.py"
PAYLOAD_TOOL_PATH = TOOLS / "stage_linux_app_payload.py"


def load_tool(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_payload_tools(test_name: str):
    worker_tool = load_tool(WORKER_TOOL_PATH, "stage_linux_worker_bundle")
    payload_tool = load_tool(PAYLOAD_TOOL_PATH, test_name)
    return worker_tool, payload_tool


def elf(machine: int) -> bytes:
    ident = b"\x7fELF" + bytes((2, 1, 1, 0, 0)) + b"\x00" * 7
    return ident + (2).to_bytes(2, "little") + machine.to_bytes(2, "little") + b"\x01\x00\x00\x00"


def context_and_hashes(worker_tool):
    _order, mapping, raw = worker_tool.parse_manifest(ROOT)
    context = worker_tool.SourceContext(
        "1" * 40,
        hashlib.sha256(raw).hexdigest(),
        worker_tool.WHISPER_GIT_COMMIT,
        worker_tool.YYJSON_GIT_COMMIT,
    )
    return context, mapping


def make_worker_bundle(tmp_path: Path, worker_tool, context, machine: int, arch: str) -> Path:
    worker = tmp_path / "worker"
    worker.write_bytes(elf(machine) + b"fixture-native-worker")
    worker.chmod(0o755)
    bundle = tmp_path / "worker-bundle"
    worker_tool.stage_from_context(worker, bundle, arch, context)
    return bundle


def test_linux_app_payload_stages_complete_python_and_worker_inventory(tmp_path: Path) -> None:
    worker_tool, payload_tool = load_payload_tools("app_payload_test")
    context, source_hashes = context_and_hashes(worker_tool)
    worker_bundle = make_worker_bundle(tmp_path, worker_tool, context, 62, "x86_64")
    output = tmp_path / "payload"

    payload_tool.stage_from_context(
        root=ROOT,
        worker_bundle_path=worker_bundle,
        output=output,
        context=context,
        source_hashes=source_hashes,
    )
    document = payload_tool.verify_from_context(
        root=ROOT,
        bundle=output,
        context=context,
        source_hashes=source_hashes,
    )

    assert (output / "app/verselatch.py").is_file()
    assert (output / "app/verselatch_core/__init__.py").is_file()
    assert (output / "app/verselatch_app/__init__.py").is_file()
    assert (output / "app/verselatch_platform/__init__.py").is_file()
    worker = output / "app/bin/verselatch-worker"
    assert worker.is_file() and not worker.is_symlink()
    assert worker.stat().st_mode & 0o777 == 0o755
    assert document["target"] == {"architecture": "x86_64", "os": "linux"}
    assert document["app"]["root"] == "app"
    assert "app/bin/verselatch-worker" in document["app"]["files"]


def test_linux_app_payload_rejects_worker_tampering(tmp_path: Path) -> None:
    worker_tool, payload_tool = load_payload_tools("app_payload_tamper_test")
    context, source_hashes = context_and_hashes(worker_tool)
    worker_bundle = make_worker_bundle(tmp_path, worker_tool, context, 183, "aarch64")
    output = tmp_path / "payload"
    payload_tool.stage_from_context(
        root=ROOT,
        worker_bundle_path=worker_bundle,
        output=output,
        context=context,
        source_hashes=source_hashes,
    )
    staged = output / "app/bin/verselatch-worker"
    staged.write_bytes(staged.read_bytes() + b"tamper")
    with pytest.raises(payload_tool.PayloadError):
        payload_tool.verify_from_context(
            root=ROOT,
            bundle=output,
            context=context,
            source_hashes=source_hashes,
        )


def test_linux_app_payload_rejects_unexpected_inventory(tmp_path: Path) -> None:
    worker_tool, payload_tool = load_payload_tools("app_payload_inventory_test")
    context, source_hashes = context_and_hashes(worker_tool)
    worker_bundle = make_worker_bundle(tmp_path, worker_tool, context, 62, "amd64")
    output = tmp_path / "payload"
    payload_tool.stage_from_context(
        root=ROOT,
        worker_bundle_path=worker_bundle,
        output=output,
        context=context,
        source_hashes=source_hashes,
    )
    (output / "app/foreign.py").write_text("foreign\n", encoding="utf-8")
    with pytest.raises(payload_tool.PayloadError):
        payload_tool.verify_from_context(
            root=ROOT,
            bundle=output,
            context=context,
            source_hashes=source_hashes,
        )


def test_linux_app_payload_source_inventory_is_only_first_party_runtime_python() -> None:
    worker_tool, payload_tool = load_payload_tools("app_payload_source_inventory_test")
    _context, source_hashes = context_and_hashes(worker_tool)
    inventory = payload_tool.source_app_inventory(ROOT, source_hashes)
    assert inventory[0] == "src/verselatch.py"
    assert any(path.startswith("src/verselatch_core/") for path in inventory)
    assert any(path.startswith("src/verselatch_app/") for path in inventory)
    assert any(path.startswith("src/verselatch_platform/") for path in inventory)
    assert all(path.endswith(".py") for path in inventory)
    assert not any(Path(path).name == "verselatch-worker" for path in inventory)


def test_linux_app_payload_rejects_nested_package_members(tmp_path: Path) -> None:
    _worker_tool, payload_tool = load_payload_tools("app_payload_nested_policy_test")
    root = tmp_path / "root"
    for rel in (
        "src/verselatch_core",
        "src/verselatch_app",
        "src/verselatch_platform",
    ):
        (root / rel).mkdir(parents=True)
    source_hashes = {
        "src/verselatch.py": "0" * 64,
        "src/verselatch_core/__init__.py": "0" * 64,
        "src/verselatch_core/nested/module.py": "0" * 64,
        "src/verselatch_app/__init__.py": "0" * 64,
        "src/verselatch_platform/__init__.py": "0" * 64,
    }
    with pytest.raises(payload_tool.PayloadError):
        payload_tool.source_app_inventory(root, source_hashes)


def test_linux_app_payload_public_cli_refuses_output_inside_source_tree(tmp_path: Path) -> None:
    _worker_tool, payload_tool = load_payload_tools("app_payload_output_policy_test")
    with pytest.raises(payload_tool.PayloadError):
        payload_tool._assert_outside_source(ROOT / "build-payload", ROOT)
