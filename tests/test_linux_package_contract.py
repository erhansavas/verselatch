# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "LINUX_PACKAGE_CONTRACT.md"


def _text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def test_linux_11_payload_is_one_atomic_owned_unit() -> None:
    text = _text()
    for required in (
        "`verselatch.py`",
        "`verselatch_core/`",
        "`verselatch_app/`",
        "`verselatch_platform/`",
        "`bin/verselatch-worker`",
        "one replacement unit",
    ):
        assert required in text


def test_linux_11_worker_is_prebuilt_package_owned_and_not_path_discovered() -> None:
    text = _text()
    assert "`bin/verselatch-worker` is package-owned" in text
    assert "must not need `whisper-cli`" in text
    assert "compiler, CMake, Ninja, Git, pip, or PATH edits" in text
    assert "does not contain a prebuilt worker binary" in text
    assert "executable regular file" in text
    assert "symbolic link" in text
    assert "does not search PATH" in text


def test_linux_11_model_and_user_data_remain_outside_app_payload() -> None:
    text = _text()
    assert "model remains outside the transactional" in text
    assert "does not silently delete the model" in text
    assert "Models, cache, logs, config, and" in text
    assert "user-created LRC files remain outside" in text


def test_linux_11_contract_preserves_historical_101_semantics() -> None:
    text = _text()
    assert "does not change or reinterpret the immutable 1.0.1" in text
    assert "valid historical 1.0.1 ownership manifest remains an upgrade input" in text
    assert "it is not" in text and "treated as a 1.1 manifest" in text


def test_linux_binary_claim_requires_arch_specific_qualified_worker() -> None:
    text = _text()
    assert "`x86_64`/`amd64`" in text
    assert "`aarch64`/`arm64`" in text
    assert "source archive is not by itself an end-user Linux binary package" in text
    assert "without relying on system `whisper-cli` or `aubio`" in text
