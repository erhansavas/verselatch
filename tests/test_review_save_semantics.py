# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.analysis import build_analysis_outcome
from verselatch_app.backend import AnalysisEvidence
from verselatch_app.session import SourceIdentity, WorkflowState


def test_manual_review_can_authorize_uncertain_draft() -> None:
    audio = SourceIdentity("audio", 1)
    outcome = build_analysis_outcome(
        audio=audio,
        lyrics=None,
        lyrics_text=None,
        evidence=AnalysisEvidence(
            segments=({"start": 0.5, "end": 1.5, "text": "silver quiet morning"},),
        ),
    )
    assert outcome.automatic_gate_passed is False

    state = WorkflowState()
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, outcome.result) is True
    assert state.save_eligible is False
    state.confirm_review(True)
    assert state.save_eligible is True
