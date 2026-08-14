# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .model import ModelVerification
from .session import SourceIdentity


@dataclass(frozen=True)
class AnalysisEvidence:
    """Validated native evidence consumed by the portable domain layer."""

    segments: tuple[dict[str, object], ...]
    beats: tuple[float, ...] = ()
    onsets: tuple[float, ...] = ()


@dataclass(frozen=True)
class EvidenceRequest:
    """Platform-neutral request for one owned native evidence job."""

    audio: SourceIdentity
    language: str
    model: ModelVerification

    def __post_init__(self) -> None:
        if not self.model.ready:
            raise ValueError("model verification required")
        if not self.language.strip():
            raise ValueError("language is required")


@runtime_checkable
class EvidenceJob(Protocol):
    """Owned backend job; implementations hide platform process mechanics."""

    def cancel(self) -> None:
        """Request cancellation of this job."""

    def result(self, timeout: float | None = None) -> AnalysisEvidence:
        """Return validated ASR/rhythm evidence or raise the backend failure."""


@runtime_checkable
class EvidenceBackend(Protocol):
    """Semantic native boundary; never exposes a generic command runner."""

    def start(self, request: EvidenceRequest) -> EvidenceJob:
        """Start exactly one VerseLatch evidence job."""
