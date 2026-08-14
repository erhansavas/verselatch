# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.backend import AnalysisEvidence
from verselatch_app.controller import AnalysisController
from verselatch_app.files import LyricsDocument, SaveReceipt
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import SourceIdentity, WorkflowState


class Job:
    def __init__(self, evidence: AnalysisEvidence, error: Exception | None = None) -> None:
        self.evidence = evidence
        self.error = error
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def result(self, timeout: float | None = None) -> AnalysisEvidence:
        if self.error is not None:
            raise self.error
        return self.evidence


class Backend:
    def __init__(self, job: Job) -> None:
        self.job = job
        self.requests = []

    def start(self, request):
        self.requests.append(request)
        return self.job


class Files:
    def __init__(self) -> None:
        self.valid: dict[SourceIdentity, bool] = {}
        self.documents: dict[SourceIdentity, LyricsDocument] = {}

    def revalidate(self, source: SourceIdentity) -> bool:
        return self.valid.get(source, True)

    def read_lyrics(self, source: SourceIdentity) -> LyricsDocument:
        return self.documents[source]

    def save_reviewed_lrc(self, request) -> SaveReceipt:
        raise AssertionError("save is outside analysis controller")


def model() -> ModelVerification:
    requirement = ModelRequirement("model.bin", 4, "abcd")
    return ModelVerification(
        requirement=requirement,
        source=SourceIdentity("model", 1),
        actual_name="model.bin",
        actual_size=4,
        actual_sha256="abcd",
    )


def test_source_change_cancels_owned_job() -> None:
    audio = SourceIdentity("audio", 1)
    newer = SourceIdentity("audio", 2)
    state = WorkflowState()
    files = Files()
    job = Job(AnalysisEvidence(segments=()))
    controller = AnalysisController(state=state, files=files, backend=Backend(job))
    controller.set_sources(audio=audio, lyrics=None)
    controller.start(model=model())

    controller.set_sources(audio=newer, lyrics=None)

    assert job.cancelled is True
    assert state.cancel_requested is True
    assert controller.finish() is None
    assert state.result is None


def test_cancellation_wins_backend_exception() -> None:
    audio = SourceIdentity("audio", 1)
    state = WorkflowState()
    files = Files()
    job = Job(AnalysisEvidence(segments=()), RuntimeError("worker stopped"))
    controller = AnalysisController(state=state, files=files, backend=Backend(job))
    controller.set_sources(audio=audio, lyrics=None)
    controller.start(model=model())
    controller.cancel()

    assert controller.finish() is None
    assert state.analysis_state == "idle"
    assert state.result is None


def test_revalidation_blocks_changed_audio_completion() -> None:
    audio = SourceIdentity("audio", 1)
    state = WorkflowState()
    files = Files()
    job = Job(AnalysisEvidence(segments=()))
    controller = AnalysisController(state=state, files=files, backend=Backend(job))
    controller.set_sources(audio=audio, lyrics=None)
    controller.start(model=model())
    files.valid[audio] = False

    assert controller.finish() is None
    assert state.result is None
