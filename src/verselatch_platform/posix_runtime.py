# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass

from verselatch_app.controller import AnalysisController
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.save import SaveController
from verselatch_app.session import WorkflowState

from .posix_backend import PosixNativeWorkerBackend
from .posix_files import PosixFileService, PosixModelService


@dataclass(frozen=True)
class PosixRuntime:
    """One explicit POSIX composition root for the portable VerseLatch workflow."""

    state: WorkflowState
    files: PosixFileService
    models: PosixModelService
    backend: PosixNativeWorkerBackend
    analysis: AnalysisController
    save: SaveController

    def verify_model(self, requirement: ModelRequirement) -> ModelVerification:
        return self.models.verify(requirement)


def create_posix_runtime(*, worker_path: str, model_path: str) -> PosixRuntime:
    """Wire one shared state/file boundary to the owned POSIX worker backend.

    Paths are explicit by design. Packaging chooses their install locations;
    the portable workflow and this composition root do not guess them.
    """
    state = WorkflowState()
    files = PosixFileService()
    models = PosixModelService(model_path)
    backend = PosixNativeWorkerBackend(worker_path)

    analysis = AnalysisController(
        state=state,
        files=files,
        backend=backend,
    )
    save = SaveController(
        state=state,
        files=files,
    )
    return PosixRuntime(
        state=state,
        files=files,
        models=models,
        backend=backend,
        analysis=analysis,
        save=save,
    )
