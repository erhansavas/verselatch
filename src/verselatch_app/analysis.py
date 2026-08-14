# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass

from verselatch_core import (
    VerseLatchError,
    align_lyrics,
    assess_generated_draft,
    parse_lyric_document,
    render_lrc,
    sanitize_generated_segments,
)
from verselatch_core.rhythm import summarize_rhythm

from .backend import AnalysisEvidence
from .session import AnalysisResult, SourceIdentity


@dataclass(frozen=True)
class AnalysisOutcome:
    """Portable domain result plus non-authoritative quality presentation data."""

    result: AnalysisResult
    kind: str
    automatic_gate_passed: bool
    details: dict[str, object]


def build_analysis_outcome(
    *,
    audio: SourceIdentity,
    lyrics: SourceIdentity | None,
    lyrics_text: str | None,
    evidence: AnalysisEvidence,
) -> AnalysisOutcome:
    """Compose native evidence using the existing portable VerseLatch domain core."""
    segments = [dict(segment) for segment in evidence.segments]
    rhythm = summarize_rhythm(list(evidence.beats), list(evidence.onsets))

    if lyrics is None:
        if lyrics_text is not None:
            raise ValueError("lyrics text requires a lyrics source")

        clean_segments, dropped_non_lyrics = sanitize_generated_segments(segments)
        draft_quality = assess_generated_draft(clean_segments)
        preview = render_lrc(
            [(segment["start"], segment["text"]) for segment in clean_segments]
        ) if clean_segments else ""

        if not clean_segments:
            kind = "generated-empty"
            automatic_gate_passed = False
        elif draft_quality["safe"]:
            kind = "generated"
            automatic_gate_passed = True
        else:
            kind = "generated-review"
            automatic_gate_passed = False

        # Automatic quality approval is deliberately not a permanent write
        # veto. A non-empty draft remains editable and can be saved only after
        # the user explicitly reviews/corrects it, matching the 1.0.1 workflow.
        result = AnalysisResult(
            preview=preview,
            audio=audio,
            lyrics=None,
            save_allowed_after_review=bool(preview.strip()),
        )
        return AnalysisOutcome(
            result=result,
            kind=kind,
            automatic_gate_passed=automatic_gate_passed,
            details={
                "draft_quality": draft_quality,
                "dropped_non_lyrics": dropped_non_lyrics,
                "rhythm": rhythm,
            },
        )

    if lyrics_text is None:
        raise ValueError("lyrics text is required for verify and align")

    document = parse_lyric_document(lyrics_text)
    lyric_entries = document["entries"]
    if not lyric_entries:
        raise VerseLatchError("Lyrics file contains no usable text.")

    alignment = align_lyrics(lyric_entries, segments)
    preview = render_lrc(alignment["rows"])
    result = AnalysisResult(
        preview=preview,
        audio=audio,
        lyrics=lyrics,
        # An automatic alignment failure still leaves source text/timing or
        # editable proposed timing for an explicit human decision.
        save_allowed_after_review=bool(preview.strip()),
    )
    return AnalysisOutcome(
        result=result,
        kind="aligned",
        automatic_gate_passed=bool(alignment["safe"]),
        details={
            "alignment": alignment,
            "rhythm": rhythm,
        },
    )
