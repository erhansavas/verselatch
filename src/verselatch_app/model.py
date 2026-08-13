# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .session import SourceIdentity


@dataclass(frozen=True)
class ModelRequirement:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelVerification:
    requirement: ModelRequirement
    source: SourceIdentity
    actual_name: str
    actual_size: int
    actual_sha256: str

    @property
    def ready(self) -> bool:
        return (
            self.actual_name == self.requirement.name
            and self.actual_size == self.requirement.size
            and self.actual_sha256.casefold() == self.requirement.sha256.casefold()
        )


@runtime_checkable
class ModelService(Protocol):
    """Verify model bytes using platform-native file handling."""

    def verify(self, requirement: ModelRequirement) -> ModelVerification:
        """Return exact verification evidence for one required model."""
