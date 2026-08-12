# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping

UNSAFE_NATIVE_ENV_KEYS = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "GCONV_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "BASH_ENV",
        "ENV",
    }
)


def native_tool_env(
    *,
    system_path: str,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a constrained inherited environment for unprivileged native tools.

    Locale, desktop-session, and hardware/backend selection variables are kept.
    Well-known dynamic-loader, Python, and shell startup injection variables are
    removed. This is defense in depth; it is not a subprocess sandbox.
    """
    env = os.environ.copy()
    for key in UNSAFE_NATIVE_ENV_KEYS:
        env.pop(key, None)
    env["PATH"] = system_path
    if extra:
        forbidden = UNSAFE_NATIVE_ENV_KEYS.intersection(extra)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ValueError(f"Unsafe native environment override refused: {names}")
        env.update(extra)
    return env


def terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float = 5.0,
) -> None:
    """Terminate one child process group, escalating to SIGKILL if necessary."""
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        # The caller owns final process bookkeeping. Returning here avoids an
        # unbounded shutdown wait if the kernel/native backend is stuck.
        pass
