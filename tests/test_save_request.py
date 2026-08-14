# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.files import SaveReceipt
from verselatch_app.save import SaveController
from verselatch_app.session import AnalysisResult, SourceIdentity, WorkflowState


class Files:
    def __init__(self) -> None:
        self.request = None

    def save_reviewed_lrc(self, request):
        self.request = request
        return SaveReceipt(SourceIdentity("output", 1), None)


def test_save_uses_exact_reviewed_content_and_sources() -> None:
    audio = SourceIdentity("audio", 1)
    state = WorkflowState()
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, AnalysisResult("[00:01.00]line\n", audio, None, True))
    state.confirm_review(True)
    files = Files()

    SaveController(state=state, files=files).save()

    assert files.request.content == state.preview
    assert files.request.audio == audio
    assert files.request.lyrics is None
