# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.backend import AnalysisEvidence
from verselatch_app.controller import AnalysisController
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import SourceIdentity, WorkflowState


class Job:
    cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def result(self, timeout=None) -> AnalysisEvidence:
        return AnalysisEvidence(segments=())


class Backend:
    def __init__(self) -> None:
        self.job = Job()

    def start(self, request):
        return self.job


class Files:
    def revalidate(self, source) -> bool:
        return True


def test_close_cancels_owned_job_and_rejects_completion() -> None:
    audio = SourceIdentity("audio", 1)
    requirement = ModelRequirement("m", 1, "aa")
    model = ModelVerification(requirement, SourceIdentity("model", 1), "m", 1, "aa")
    state = WorkflowState()
    backend = Backend()
    controller = AnalysisController(state=state, files=Files(), backend=backend)
    controller.set_sources(audio=audio, lyrics=None)
    controller.start(model=model)

    controller.begin_close()

    assert backend.job.cancelled is True
    assert controller.finish() is None
    assert state.analysis_state == "closing"
    assert state.result is None
