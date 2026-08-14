# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.analysis import build_analysis_outcome
from verselatch_app.backend import AnalysisEvidence
from verselatch_app.session import SourceIdentity


def source(name: str) -> SourceIdentity:
    return SourceIdentity(name, ("revision", 1))


def test_uncertain_generated_draft_remains_review_savable() -> None:
    audio = source("content://audio/1")
    evidence = AnalysisEvidence(
        segments=({"start": 0.5, "end": 1.5, "text": "silver quiet morning"},),
    )
    outcome = build_analysis_outcome(
        audio=audio,
        lyrics=None,
        lyrics_text=None,
        evidence=evidence,
    )
    assert outcome.kind == "generated-review"
    assert outcome.automatic_gate_passed is False
    assert outcome.result.preview
    assert outcome.result.save_allowed_after_review is True


def test_non_lyric_only_generation_is_not_savable() -> None:
    audio = source("content://audio/2")
    evidence = AnalysisEvidence(
        segments=({"start": 0.0, "end": 1.0, "text": "[music]"},),
    )
    outcome = build_analysis_outcome(
        audio=audio,
        lyrics=None,
        lyrics_text=None,
        evidence=evidence,
    )
    assert outcome.kind == "generated-empty"
    assert outcome.result.preview == ""
    assert outcome.result.save_allowed_after_review is False
