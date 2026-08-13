# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.backend import AnalysisEvidence
from verselatch_app.controller import AnalysisController
from verselatch_app.files import LyricsDocument
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import SourceIdentity, WorkflowState


class Job:
    def cancel(self) -> None:
        pass

    def result(self, timeout: float | None = None) -> AnalysisEvidence:
        return AnalysisEvidence(segments=())


class Backend:
    def start(self, request):
        return Job()


class Files:
    def __init__(self, document: LyricsDocument | None = None) -> None:
        self.document = document

    def revalidate(self, source: SourceIdentity) -> bool:
        return True

    def read_lyrics(self, source: SourceIdentity) -> LyricsDocument:
        assert self.document is not None
        return self.document


def verified_model() -> ModelVerification:
    req = ModelRequirement("m", 1, "aa")
    return ModelVerification(req, SourceIdentity("model", 1), "m", 1, "aa")


def test_lyrics_read_identity_must_match_selection() -> None:
    audio = SourceIdentity("audio", 1)
    lyrics = SourceIdentity("lyrics", 1)
    replaced = SourceIdentity("lyrics", 2)
    state = WorkflowState()
    state.set_sources(audio=audio, lyrics=lyrics)
    controller = AnalysisController(
        state=state,
        files=Files(LyricsDocument(source=replaced, text="line")),
        backend=Backend(),
    )

    with pytest.raises(RuntimeError, match="changed"):
        controller.start(model=verified_model())
    assert state.analysis_state == "idle"


def test_successful_generate_completion_belongs_to_selected_audio() -> None:
    audio = SourceIdentity("audio", 1)
    state = WorkflowState()
    state.set_sources(audio=audio, lyrics=None)
    controller = AnalysisController(state=state, files=Files(), backend=Backend())
    controller.start(model=verified_model())

    outcome = controller.finish()

    assert outcome is not None
    assert outcome.kind == "generated-empty"
    assert state.result == outcome.result
    assert state.result.audio == audio
