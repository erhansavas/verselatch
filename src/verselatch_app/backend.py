# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .model import ModelVerification
from .session import AnalysisResult, SourceIdentity


@dataclass(frozen=True)
class AnalysisRequest:
    """Platform-neutral request for one owned analysis job."""

    audio: SourceIdentity
    lyrics: SourceIdentity | None
    language: str
    model: ModelVerification

    def __post_init__(self) -> None:
        if not self.model.ready:
            raise ValueError("model verification required")


@runtime_checkable
class AnalysisJob(Protocol):
    """Owned backend job; implementations hide platform process mechanics."""

    def cancel(self) -> None:
        """Request cancellation of this job."""

    def result(self, timeout: float | None = None) -> AnalysisResult:
        """Return the validated result or raise the backend failure."""


@runtime_checkable
class AnalysisBackend(Protocol):
    """Semantic backend boundary; deliberately not a generic command runner."""

    def start(self, request: AnalysisRequest) -> AnalysisJob:
        """Start exactly one VerseLatch analysis job."""
