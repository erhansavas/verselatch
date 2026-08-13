# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.session import AnalysisResult, SourceIdentity, WorkflowState


def test_analysis_state_is_derived_from_workflow() -> None:
    state = WorkflowState()
    source = SourceIdentity("song.flac", 1)
    state.set_sources(audio=source, lyrics=None)
    assert state.analysis_state == "idle"

    run_id = state.begin_analysis()
    assert state.analysis_state == "running"
    state.request_cancel()
    assert state.analysis_state == "cancelling"
    assert state.finish_cancelled(run_id) is True
    assert state.analysis_state == "idle"

    run_id = state.begin_analysis()
    result = AnalysisResult(
        preview="[00:01.00]line\n",
        audio=source,
        lyrics=None,
        save_allowed_after_review=True,
    )
    assert state.finish_analysis(run_id, result) is True
    assert state.analysis_state == "completed"

    state.begin_close()
    assert state.analysis_state == "closing"
