# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from verselatch_core import VerseLatchError, safe_read_text, safe_write_lrc


def test_safe_read_text_rejects_symlink_and_special_file(tmp_path: Path):
    source = tmp_path / "lyrics.lrc"
    source.write_text("[00:01.00]line\n", encoding="utf-8")
    link = tmp_path / "link.lrc"
    link.symlink_to(source)
    with pytest.raises(VerseLatchError):
        safe_read_text(link)

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo.lrc"
        os.mkfifo(fifo)
        with pytest.raises(VerseLatchError):
            safe_read_text(fifo)


def test_safe_write_is_atomic_and_preserves_existing_mode(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"audio")
    output = tmp_path / "song.lrc"
    output.write_text("old\n", encoding="utf-8")
    output.chmod(0o640)

    saved, backup = safe_write_lrc(audio, "new")
    assert saved == output
    assert saved.read_text(encoding="utf-8") == "new\n"
    assert backup is not None
    assert backup.read_text(encoding="utf-8") == "old\n"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o640
    assert stat.S_IMODE(backup.stat().st_mode) == 0o640
    assert not list(tmp_path.glob(".song.lrc.*.tmp"))


def test_safe_write_refuses_symlink_destination_without_touching_victim(tmp_path: Path):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"audio")
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    output = tmp_path / "song.lrc"
    output.symlink_to(victim)

    with pytest.raises(VerseLatchError):
        safe_write_lrc(audio, "replacement")
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_safe_write_does_not_mutate_audio_source(tmp_path: Path):
    audio = tmp_path / "song.flac"
    original = b"source-bytes"
    audio.write_bytes(original)
    safe_write_lrc(audio, "[00:01.00]line")
    assert audio.read_bytes() == original


def test_atomic_write_failure_before_replace_preserves_existing_lrc(tmp_path, monkeypatch):
    import verselatch_core.storage as storage

    audio = tmp_path / "song.flac"
    output = tmp_path / "song.lrc"
    audio.write_bytes(b"audio")
    output.write_text("old content\n", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        storage.safe_write_lrc(audio, "new content")

    assert output.read_text(encoding="utf-8") == "old content\n"
    assert not list(tmp_path.glob(".song.lrc.*.tmp"))
    backups = list(tmp_path.glob("song.lrc.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old content\n"


def test_regular_file_state_guard_detects_source_mutation(tmp_path: Path):
    from verselatch_core.storage import regular_file_state, require_regular_file_state

    source = tmp_path / "source.txt"
    source.write_text("first\n", encoding="utf-8")
    state = regular_file_state(source, description="Source", maximum_bytes=1024)
    require_regular_file_state(source, state, description="Source", maximum_bytes=1024)

    source.write_text("second and changed\n", encoding="utf-8")
    with pytest.raises(VerseLatchError, match="changed after it was selected"):
        require_regular_file_state(source, state, description="Source", maximum_bytes=1024)


@pytest.mark.parametrize(
    "filename",
    [
        "song with spaces.flac",
        "-leading-dash.flac",
        "quote-\"-name.flac",
        "Türkçe-şarkı.flac",
        "dollar-$-literal.flac",
    ],
)
def test_atomic_save_treats_unusual_valid_filenames_as_data(tmp_path: Path, filename: str):
    audio = tmp_path / filename
    audio.write_bytes(b"audio")
    saved, backup = safe_write_lrc(audio, "[00:01.00]güvenli satır")
    assert backup is None
    assert saved == audio.with_suffix(".lrc")
    assert saved.read_text(encoding="utf-8") == "[00:01.00]güvenli satır\n"


def test_public_storage_state_api_detects_replacement(tmp_path: Path):
    from verselatch_core.storage import regular_file_state, require_regular_file_state

    source = tmp_path / "selected.txt"
    source.write_text("one", encoding="utf-8")
    state = regular_file_state(source, description="Selected", maximum_bytes=1024)
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("two", encoding="utf-8")
    replacement.replace(source)
    with pytest.raises(VerseLatchError, match="changed after it was selected"):
        require_regular_file_state(source, state, description="Selected", maximum_bytes=1024)
