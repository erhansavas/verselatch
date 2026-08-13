# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_file_exists() -> None:
    assert (ROOT / "SHA256SUMS").is_file()
