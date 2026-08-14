# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.save import SaveController
from verselatch_app.session import AnalysisResult, SourceIdentity, WorkflowState


class Files:
    def save_reviewed_lrc(self, request):
        raise AssertionError("save must not be reached")


def test_save_requires_explicit_review() -> None:
    audio = SourceIdentity("audio", 1)
    state = WorkflowState()
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, AnalysisResult("[00:01.00]line\n", audio, None, True))

    with pytest.raises(RuntimeError, match="not eligible"):
        SaveController(state=state, files=Files()).save()
