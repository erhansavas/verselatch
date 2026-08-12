# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from verselatch_core.process import (
    UNSAFE_NATIVE_ENV_KEYS,
    native_tool_env,
    terminate_process_group,
)


def test_native_tool_environment_strips_injection_but_preserves_normal_context(monkeypatch):
    for key in UNSAFE_NATIVE_ENV_KEYS:
        monkeypatch.setenv(key, "unsafe")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    monkeypatch.setenv("GGML_VK_VISIBLE_DEVICES", "0")

    env = native_tool_env(
        system_path="/usr/bin:/bin",
        extra={"OMP_NUM_THREADS": "2"},
    )

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["LANG"] == "tr_TR.UTF-8"
    assert env["GGML_VK_VISIBLE_DEVICES"] == "0"
    assert env["OMP_NUM_THREADS"] == "2"
    assert not UNSAFE_NATIVE_ENV_KEYS.intersection(env)


def test_native_tool_environment_refuses_reintroducing_unsafe_override():
    with pytest.raises(ValueError, match="LD_PRELOAD"):
        native_tool_env(
            system_path="/usr/bin:/bin",
            extra={"LD_PRELOAD": "/tmp/evil.so"},
        )


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="POSIX process groups are required")
def test_terminate_process_group_stops_unprivileged_child():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.03)
        terminate_process_group(process, grace_seconds=0.3)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
