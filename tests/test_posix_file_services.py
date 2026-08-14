# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from verselatch_app.files import SaveRequest
from verselatch_app.model import ModelRequirement
from verselatch_core.errors import VerseLatchError
from verselatch_platform.posix_files import (
    PosixFileRevision,
    PosixFileService,
    PosixModelService,
)


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file adapter")


def test_identify_and_revalidate_audio(tmp_path: Path) -> None:
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")
    service = PosixFileService()

    source = service.identify_audio(str(audio))
    assert isinstance(source.revision, PosixFileRevision)
    assert source.revision.kind == "audio"
    assert service.revalidate(source)

    audio.write_bytes(b"changed")
    assert not service.revalidate(source)


def test_audio_symlink_and_relative_paths_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.wav"
    target.write_bytes(b"audio")
    link = tmp_path / "link.wav"
    link.symlink_to(target)
    service = PosixFileService()

    with pytest.raises(VerseLatchError):
        service.identify_audio(str(link))
    with pytest.raises(VerseLatchError, match="absolute"):
        service.identify_audio("relative.wav")


def test_bounded_lyrics_read_reports_actual_identity(tmp_path: Path) -> None:
    lyrics = tmp_path / "song.lrc"
    lyrics.write_text("[00:01.00]hello\n", encoding="utf-8")
    service = PosixFileService()

    source = service.identify_lyrics(str(lyrics))
    document = service.read_lyrics(source)

    assert document.source == source
    assert document.text == "[00:01.00]hello\n"


def test_safe_save_creates_output_and_backup(tmp_path: Path) -> None:
    audio = tmp_path / "song.wav"
    output = tmp_path / "song.lrc"
    audio.write_bytes(b"audio")
    output.write_text("[00:00.00]old\n", encoding="utf-8")

    service = PosixFileService()
    audio_source = service.identify_audio(str(audio))
    lyrics_source = service.identify_lyrics(str(output))

    receipt = service.save_reviewed_lrc(
        SaveRequest(
            content="[00:01.00]new",
            audio=audio_source,
            lyrics=lyrics_source,
        )
    )

    assert Path(receipt.output.location) == output
    assert output.read_text(encoding="utf-8") == "[00:01.00]new\n"
    assert receipt.backup is not None
    backup = Path(receipt.backup.location)
    assert backup.read_text(encoding="utf-8") == "[00:00.00]old\n"


def test_safe_save_rejects_stale_audio(tmp_path: Path) -> None:
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")
    service = PosixFileService()
    source = service.identify_audio(str(audio))

    audio.write_bytes(b"changed")
    with pytest.raises(VerseLatchError):
        service.save_reviewed_lrc(
            SaveRequest(
                content="[00:01.00]new",
                audio=source,
                lyrics=None,
            )
        )
    assert not (tmp_path / "song.lrc").exists()


def test_model_service_verifies_exact_bytes_and_detects_wrong_digest(tmp_path: Path) -> None:
    model = tmp_path / "ggml-large-v3-turbo.bin"
    data = b"model-fixture"
    model.write_bytes(data)
    service = PosixModelService(str(model))

    exact = ModelRequirement(
        name=model.name,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    verified = service.verify(exact)
    assert verified.ready
    assert isinstance(verified.source.revision, PosixFileRevision)
    assert verified.source.revision.kind == "model"

    wrong = ModelRequirement(
        name=model.name,
        size=len(data),
        sha256="0" * 64,
    )
    assert not service.verify(wrong).ready


def test_model_service_skips_hash_when_size_is_wrong(tmp_path: Path) -> None:
    model = tmp_path / "ggml-large-v3-turbo.bin"
    model.write_bytes(b"x")
    service = PosixModelService(str(model))
    requirement = ModelRequirement(
        name=model.name,
        size=2,
        sha256="0" * 64,
    )
    result = service.verify(requirement)
    assert result.actual_size == 1
    assert result.actual_sha256 == ""
    assert not result.ready
