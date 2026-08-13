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


def _analysis_source_fixture(tmp_path: Path):
    from verselatch_core.storage import regular_file_state

    audio = tmp_path / "song.flac"
    lyrics = tmp_path / "song-source.lrc"
    audio.write_bytes(b"audio")
    lyrics.write_text("[00:01.00]line\n", encoding="utf-8")
    return (
        audio,
        regular_file_state(audio, description="Audio source", maximum_bytes=1024),
        lyrics,
        regular_file_state(lyrics, description="Lyrics source", maximum_bytes=1024),
    )


def _require_analysis_sources(*, audio, audio_state, lyrics, lyrics_state, current_lyrics=None):
    from verselatch_core.storage import require_analysis_source_states

    require_analysis_source_states(
        current_audio_path=audio,
        analyzed_audio_path=audio,
        analyzed_audio_state=audio_state,
        current_lyrics_path=lyrics if current_lyrics is None else current_lyrics,
        analyzed_lyrics_path=lyrics,
        analyzed_lyrics_state=lyrics_state,
        maximum_audio_bytes=1024,
        maximum_lyrics_bytes=1024,
    )


def test_analysis_source_guard_allows_unchanged_lyrics(tmp_path: Path):
    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    _require_analysis_sources(
        audio=audio,
        audio_state=audio_state,
        lyrics=lyrics,
        lyrics_state=lyrics_state,
    )


def test_analysis_source_guard_rejects_lyrics_changed_after_analysis(tmp_path: Path):
    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    lyrics.write_text("[00:02.00]external edit after analysis\n", encoding="utf-8")
    with pytest.raises(VerseLatchError, match="Lyrics changed or became unsafe after analysis"):
        _require_analysis_sources(
            audio=audio,
            audio_state=audio_state,
            lyrics=lyrics,
            lyrics_state=lyrics_state,
        )


def test_analysis_source_guard_rejects_lyrics_inode_replacement(tmp_path: Path):
    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    replacement = tmp_path / "replacement.lrc"
    replacement.write_text("[00:01.00]line\n", encoding="utf-8")
    replacement.replace(lyrics)
    with pytest.raises(VerseLatchError, match="Lyrics changed or became unsafe after analysis"):
        _require_analysis_sources(
            audio=audio,
            audio_state=audio_state,
            lyrics=lyrics,
            lyrics_state=lyrics_state,
        )


def test_analysis_source_guard_rejects_removed_lyrics(tmp_path: Path):
    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    lyrics.unlink()
    with pytest.raises(VerseLatchError, match="Lyrics changed or became unsafe after analysis"):
        _require_analysis_sources(
            audio=audio,
            audio_state=audio_state,
            lyrics=lyrics,
            lyrics_state=lyrics_state,
        )


def test_analysis_source_guard_still_rejects_stale_audio(tmp_path: Path):
    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    audio.write_bytes(b"changed audio")
    with pytest.raises(VerseLatchError, match="Audio changed or became unsafe after analysis"):
        _require_analysis_sources(
            audio=audio,
            audio_state=audio_state,
            lyrics=lyrics,
            lyrics_state=lyrics_state,
        )


def test_analysis_source_guard_allows_generate_draft_without_lyrics(tmp_path: Path):
    from verselatch_core.storage import regular_file_state, require_analysis_source_states

    audio = tmp_path / "song.flac"
    audio.write_bytes(b"audio")
    state = regular_file_state(audio, description="Audio source", maximum_bytes=1024)
    require_analysis_source_states(
        current_audio_path=audio,
        analyzed_audio_path=audio,
        analyzed_audio_state=state,
        current_lyrics_path=None,
        analyzed_lyrics_path=None,
        analyzed_lyrics_state=None,
        maximum_audio_bytes=1024,
        maximum_lyrics_bytes=1024,
    )


def test_analysis_source_guard_rejects_selection_path_mixup(tmp_path: Path):
    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    other = tmp_path / "other.lrc"
    other.write_text("[00:01.00]line\n", encoding="utf-8")
    with pytest.raises(VerseLatchError, match="Lyrics selection changed after analysis"):
        _require_analysis_sources(
            audio=audio,
            audio_state=audio_state,
            lyrics=lyrics,
            lyrics_state=lyrics_state,
            current_lyrics=other,
        )


def test_reviewed_save_rejects_stale_lyrics_before_touching_output(tmp_path: Path):
    from verselatch_core.storage import safe_write_reviewed_lrc

    audio, audio_state, lyrics, lyrics_state = _analysis_source_fixture(tmp_path)
    output = audio.with_suffix(".lrc")
    output.write_text("existing output\n", encoding="utf-8")
    lyrics.write_text("[00:03.00]changed after analysis\n", encoding="utf-8")

    with pytest.raises(VerseLatchError, match="Lyrics changed or became unsafe after analysis"):
        safe_write_reviewed_lrc(
            content="[00:01.00]stale preview",
            current_audio_path=audio,
            analyzed_audio_path=audio,
            analyzed_audio_state=audio_state,
            current_lyrics_path=lyrics,
            analyzed_lyrics_path=lyrics,
            analyzed_lyrics_state=lyrics_state,
            maximum_audio_bytes=1024,
            maximum_lyrics_bytes=1024,
        )
    assert output.read_text(encoding="utf-8") == "existing output\n"
    assert not list(tmp_path.glob("song.lrc.bak-*"))


def test_reviewed_save_generate_draft_without_lyrics_writes_normally(tmp_path: Path):
    from verselatch_core.storage import regular_file_state, safe_write_reviewed_lrc

    audio = tmp_path / "draft.flac"
    audio.write_bytes(b"audio")
    state = regular_file_state(audio, description="Audio source", maximum_bytes=1024)
    output, backup = safe_write_reviewed_lrc(
        content="[00:01.00]draft line",
        current_audio_path=audio,
        analyzed_audio_path=audio,
        analyzed_audio_state=state,
        current_lyrics_path=None,
        analyzed_lyrics_path=None,
        analyzed_lyrics_state=None,
        maximum_audio_bytes=1024,
        maximum_lyrics_bytes=1024,
    )
    assert backup is None
    assert output.read_text(encoding="utf-8") == "[00:01.00]draft line\n"
