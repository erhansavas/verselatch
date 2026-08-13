# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .session import SourceIdentity


@dataclass(frozen=True)
class LyricsDocument:
    """Bounded lyric text together with the identity actually read."""

    source: SourceIdentity
    text: str


@dataclass(frozen=True)
class SaveRequest:
    """Reviewed content plus the exact sources that authorized the result."""

    content: str
    audio: SourceIdentity
    lyrics: SourceIdentity | None


@dataclass(frozen=True)
class SaveReceipt:
    """Opaque platform resources created by a successful Save operation."""

    output: SourceIdentity
    backup: SourceIdentity | None


@runtime_checkable
class FileService(Protocol):
    """Small semantic source/save boundary; not a generic filesystem API."""

    def revalidate(self, source: SourceIdentity) -> bool:
        """Return whether the selected source still has the same identity."""

    def read_lyrics(self, source: SourceIdentity) -> LyricsDocument:
        """Read bounded lyrics and report the identity of bytes actually read."""

    def save_reviewed_lrc(self, request: SaveRequest) -> SaveReceipt:
        """Revalidate analysis sources and perform a safe platform-native save."""
