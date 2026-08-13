# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.analysis import build_analysis_outcome
from verselatch_app.backend import AnalysisEvidence
from verselatch_app.session import SourceIdentity


def test_safe_generated_draft_passes_gate_and_still_needs_review() -> None:
    audio = SourceIdentity("audio", 1)
    outcome = build_analysis_outcome(
        audio=audio,
        lyrics=None,
        lyrics_text=None,
        evidence=AnalysisEvidence(
            segments=(
                {
                    "start": 0.5,
                    "end": 1.5,
                    "text": "silver quiet morning",
                    "token_confidence": 0.9,
                    "low_confidence_fraction": 0.0,
                    "token_count": 3,
                },
            ),
        ),
    )

    assert outcome.kind == "generated"
    assert outcome.automatic_gate_passed is True
    assert outcome.result.save_allowed_after_review is True
