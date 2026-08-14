# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.session import AnalysisResult, SourceIdentity, WorkflowState


def make_audio() -> SourceIdentity:
    return SourceIdentity("song.flac", 1)


def make_result(source: SourceIdentity) -> AnalysisResult:
    return AnalysisResult(
        preview="[00:01.00]line\n",
        audio=source,
        lyrics=None,
        save_allowed_after_review=True,
    )


def test_shutdown_invalidates_reviewed_output() -> None:
    state = WorkflowState()
    source = make_audio()
    state.set_sources(audio=source, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, make_result(source)) is True
    state.confirm_review(True)
    assert state.save_eligible is True

    state.begin_close()

    assert state.closing is True
    assert state.result is None
    assert state.preview == ""
    assert state.review_confirmed is False
    assert state.save_eligible is False


def test_shutdown_rejects_late_analysis_result() -> None:
    state = WorkflowState()
    source = make_audio()
    state.set_sources(audio=source, lyrics=None)
    run_id = state.begin_analysis()

    state.begin_close()

    assert state.cancel_requested is True
    assert state.finish_analysis(run_id, make_result(source)) is False
    assert state.active_run_id is None
    assert state.result is None
    assert state.save_eligible is False


def test_shutdown_blocks_new_analysis() -> None:
    state = WorkflowState()
    state.set_sources(audio=make_audio(), lyrics=None)
    state.begin_close()

    with pytest.raises(RuntimeError, match="closing"):
        state.begin_analysis()
