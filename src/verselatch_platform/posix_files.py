# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Final

from verselatch_app.files import FileService, LyricsDocument, SaveReceipt, SaveRequest
from verselatch_app.model import ModelRequirement, ModelService, ModelVerification
from verselatch_app.session import SourceIdentity
from verselatch_core.constants import MAX_LYRICS_BYTES
from verselatch_core.errors import VerseLatchError
from verselatch_core.storage import (
    file_state_tuple,
    open_regular_readonly,
    safe_write_reviewed_lrc,
)


MAX_AUDIO_BYTES: Final = 512 * 1024 * 1024
_HASH_CHUNK_BYTES: Final = 1024 * 1024
_AUDIO_SUFFIXES: Final = frozenset({".flac", ".mp3", ".ogg", ".wav"})
_LYRICS_SUFFIXES: Final = frozenset({".lrc", ".txt"})
_REVISION_SCHEMA: Final = 1


@dataclass(frozen=True)
class PosixFileRevision:
    schema: int
    kind: str
    state: tuple[int, int, int, int, int]

    def __post_init__(self) -> None:
        if self.schema != _REVISION_SCHEMA:
            raise ValueError("unsupported POSIX file revision schema")
        if self.kind not in {"audio", "lyrics", "model"}:
            raise ValueError("unsupported POSIX file revision kind")
        if len(self.state) != 5 or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in self.state
        ):
            raise ValueError("invalid POSIX file revision state")


def _absolute_path(location: str) -> Path:
    if "\x00" in location:
        raise VerseLatchError("Local file path contains a NUL byte.")
    path = Path(location)
    if not path.is_absolute():
        raise VerseLatchError("Local file path must be absolute.")
    return path


def _source_from_open(
    path: Path,
    *,
    kind: str,
    maximum_bytes: int | None,
) -> SourceIdentity:
    descriptor = -1
    try:
        descriptor, metadata = open_regular_readonly(
            path,
            description=f"{kind.capitalize()} source",
            maximum_bytes=maximum_bytes,
        )
        revision = PosixFileRevision(
            schema=_REVISION_SCHEMA,
            kind=kind,
            state=file_state_tuple(metadata),
        )
        return SourceIdentity(location=str(path), revision=revision)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _require_revision(source: SourceIdentity, kind: str) -> PosixFileRevision:
    revision = source.revision
    if not isinstance(revision, PosixFileRevision) or revision.kind != kind:
        raise VerseLatchError(f"{kind.capitalize()} source identity is invalid.")
    return revision


class PosixFileService(FileService):
    """POSIX local-file adapter for selection identity, bounded lyrics, and safe Save."""

    def identify_audio(self, location: str) -> SourceIdentity:
        path = _absolute_path(location)
        if path.suffix.casefold() not in _AUDIO_SUFFIXES:
            raise VerseLatchError("Unsupported audio file type.")
        return _source_from_open(
            path,
            kind="audio",
            maximum_bytes=MAX_AUDIO_BYTES,
        )

    def identify_lyrics(self, location: str) -> SourceIdentity:
        path = _absolute_path(location)
        if path.suffix.casefold() not in _LYRICS_SUFFIXES:
            raise VerseLatchError("Unsupported lyrics file type.")
        return _source_from_open(
            path,
            kind="lyrics",
            maximum_bytes=MAX_LYRICS_BYTES,
        )

    def revalidate(self, source: SourceIdentity) -> bool:
        revision = source.revision
        if not isinstance(revision, PosixFileRevision):
            return False
        if revision.kind == "audio":
            maximum = MAX_AUDIO_BYTES
        elif revision.kind == "lyrics":
            maximum = MAX_LYRICS_BYTES
        else:
            return False

        descriptor = -1
        try:
            path = _absolute_path(source.location)
            descriptor, metadata = open_regular_readonly(
                path,
                description=f"{revision.kind.capitalize()} source",
                maximum_bytes=maximum,
            )
            return file_state_tuple(metadata) == revision.state
        except (OSError, VerseLatchError):
            return False
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def read_lyrics(self, source: SourceIdentity) -> LyricsDocument:
        revision = _require_revision(source, "lyrics")
        path = _absolute_path(source.location)
        descriptor = -1
        try:
            descriptor, metadata = open_regular_readonly(
                path,
                description="Lyrics source",
                maximum_bytes=MAX_LYRICS_BYTES,
            )
            before = file_state_tuple(metadata)
            if before != revision.state:
                raise VerseLatchError("Lyrics source changed before it was read.")

            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                data = handle.read(MAX_LYRICS_BYTES + 1)
                after = file_state_tuple(os.fstat(handle.fileno()))

            if len(data) > MAX_LYRICS_BYTES:
                raise VerseLatchError("Lyrics file exceeds the safety size limit.")
            if after != before:
                raise VerseLatchError("Lyrics source changed while it was being read.")

            actual_source = SourceIdentity(
                location=str(path),
                revision=PosixFileRevision(
                    schema=_REVISION_SCHEMA,
                    kind="lyrics",
                    state=after,
                ),
            )
            return LyricsDocument(
                source=actual_source,
                text=data.decode("utf-8", errors="replace"),
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def save_reviewed_lrc(self, request: SaveRequest) -> SaveReceipt:
        audio_revision = _require_revision(request.audio, "audio")
        audio_path = _absolute_path(request.audio.location)

        lyrics_path: Path | None = None
        lyrics_state: tuple[int, int, int, int, int] | None = None
        if request.lyrics is not None:
            lyrics_revision = _require_revision(request.lyrics, "lyrics")
            lyrics_path = _absolute_path(request.lyrics.location)
            lyrics_state = lyrics_revision.state

        output, backup = safe_write_reviewed_lrc(
            content=request.content,
            current_audio_path=audio_path,
            analyzed_audio_path=audio_path,
            analyzed_audio_state=audio_revision.state,
            current_lyrics_path=lyrics_path,
            analyzed_lyrics_path=lyrics_path,
            analyzed_lyrics_state=lyrics_state,
            maximum_audio_bytes=MAX_AUDIO_BYTES,
            maximum_lyrics_bytes=MAX_LYRICS_BYTES,
        )

        return SaveReceipt(
            output=_source_from_open(
                output,
                kind="lyrics",
                maximum_bytes=MAX_LYRICS_BYTES,
            ),
            backup=(
                _source_from_open(
                    backup,
                    kind="lyrics",
                    maximum_bytes=MAX_LYRICS_BYTES,
                )
                if backup is not None
                else None
            ),
        )


class PosixModelService(ModelService):
    """Verify one configured local model with a single no-follow open descriptor."""

    def __init__(self, model_path: str) -> None:
        self._model_path = _absolute_path(model_path)

    def verify(self, requirement: ModelRequirement) -> ModelVerification:
        descriptor = -1
        try:
            descriptor, metadata = open_regular_readonly(
                self._model_path,
                description="ASR model",
            )
            before = file_state_tuple(metadata)
            source = SourceIdentity(
                location=str(self._model_path),
                revision=PosixFileRevision(
                    schema=_REVISION_SCHEMA,
                    kind="model",
                    state=before,
                ),
            )

            actual_sha256 = ""
            if (
                self._model_path.name == requirement.name
                and metadata.st_size == requirement.size
            ):
                digest = hashlib.sha256()
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    while True:
                        chunk = handle.read(_HASH_CHUNK_BYTES)
                        if not chunk:
                            break
                        digest.update(chunk)
                    after = file_state_tuple(os.fstat(handle.fileno()))
                if after != before:
                    raise VerseLatchError("ASR model changed while it was being verified.")
                actual_sha256 = digest.hexdigest()

            return ModelVerification(
                requirement=requirement,
                source=source,
                actual_name=self._model_path.name,
                actual_size=metadata.st_size,
                actual_sha256=actual_sha256,
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
