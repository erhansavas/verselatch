# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "validate_appstream.sh"


def _run_with_fake_validator(tmp_path: Path, output: str, status: int, *args: str):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "appstreamcli"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f"cat <<'EOF'\n{output}\nEOF\n"
        f"exit {status}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(HELPER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_public_appstream_policy_is_the_default_and_accepts_clean_validation(tmp_path):
    result = _run_with_fake_validator(
        tmp_path,
        "✓ Validation was successful: no issues found",
        0,
    )
    assert result.returncode == 0, result.stdout


def test_public_appstream_policy_rejects_any_validator_failure(tmp_path):
    result = _run_with_fake_validator(
        tmp_path,
        "W: io.github.erhansavas.verselatch:~: releases-info-missing\n"
        "✘ Validation failed: warnings: 1",
        3,
        "--public",
    )
    assert result.returncode != 0


def test_private_policy_rejects_public_metadata(tmp_path):
    result = _run_with_fake_validator(
        tmp_path,
        "✓ Validation was successful: no issues found",
        0,
        "--private",
    )
    assert result.returncode != 0
    assert "Private-RC metadata must not contain an unverified homepage URL" in result.stdout
