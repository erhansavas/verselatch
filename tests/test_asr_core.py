# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import pytest

from verselatch_core import (
    assess_generated_draft,
    parse_whisper_json,
    sanitize_generated_segments,
    validate_asr_segments,
)


def test_whisper_json_rejects_wrong_container_and_nonfinite_offsets():
    assert parse_whisper_json({"transcription": "not-a-list"}) == []
    assert parse_whisper_json({"transcription": [None, 3, {"text": 7}]}) == []

    parsed = parse_whisper_json(
        {"transcription": [{"text": "valid", "offsets": {"from": 1000, "to": 2000}}]}
    )
    assert parsed[0]["text"] == "valid"
    assert all(segment["start"] >= 0 for segment in parsed)
    assert all(segment["end"] >= segment["start"] for segment in parsed)

    # The cache/parser boundary is intentionally fail-closed: one malformed
    # segment invalidates the whole candidate stream instead of silently
    # mixing trusted and untrusted timing evidence.
    assert parse_whisper_json(
        {"transcription": [{"text": "nan", "offsets": {"from": "nan", "to": 2000}}]}
    ) == []


def test_native_word_timing_is_retained_only_when_dense_enough():
    parsed = parse_whisper_json(
        {
            "transcription": [
                {
                    "text": " silver morning",
                    "offsets": {"from": 1000, "to": 2200},
                    "tokens": [
                        {"text": " silver", "p": 0.90, "offsets": {"from": 1100, "to": 1500}},
                        {"text": " morning", "p": 0.80, "offsets": {"from": 1550, "to": 2100}},
                    ],
                }
            ]
        }
    )
    assert parsed[0]["words"] == [
        {"text": "silver", "start": 1.1, "end": 1.5},
        {"text": "morning", "start": 1.55, "end": 2.1},
    ]


def test_stage_cues_are_removed_without_rewriting_real_lyrics():
    clean, dropped = sanitize_generated_segments(
        [
            {"start": 0.0, "end": 1.0, "text": "[MÜZİK ÇALIYOR]"},
            {"start": 1.0, "end": 2.0, "text": "♪♫"},
            {"start": 2.0, "end": 3.0, "text": "silver morning"},
        ]
    )
    assert dropped == 2
    assert [item["text"] for item in clean] == ["silver morning"]


def test_generated_draft_fails_closed_on_repetition_and_weak_confidence():
    runaway = {
        "start": 0.0,
        "end": 30.0,
        "text": "alpha beta gamma delta " * 12,
        "token_confidence": 0.62,
        "low_confidence_fraction": 0.10,
        "token_count": 48,
    }
    report = assess_generated_draft([runaway])
    assert not report["safe"]
    assert report["severe_count"] >= 1

    weak = {
        "start": 0.0,
        "end": 3.0,
        "text": "silver morning quiet water",
        "token_confidence": 0.20,
        "low_confidence_fraction": 0.90,
        "token_count": 4,
    }
    assert not assess_generated_draft([weak])["safe"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_asr_validation_rejects_nonfinite_native_numeric_values(bad):
    assert validate_asr_segments([{"start": bad, "end": 2.0, "text": "line"}]) is None
    assert validate_asr_segments([{"start": 1.0, "end": bad, "text": "line"}]) is None
