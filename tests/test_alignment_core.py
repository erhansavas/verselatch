# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import copy

import pytest

from verselatch_core import VerseLatchError, align_lyrics, parse_lyric_document


def _fictional_entries():
    return parse_lyric_document(
        "\n".join(
            [
                "[00:01.12]silver morning",
                "[00:08.31]quiet satellite",
                "[00:15.57]paper horizon",
                "[00:22.04]distant lantern",
                "[00:29.46]amber window",
                "[00:36.77]winter signal",
                "[00:43.09]soft horizon",
                "[00:50.63]open water",
                "[00:57.28]northbound echo",
                "[01:04.91]final lantern",
            ]
        )
    )["entries"]


def test_alignment_is_deterministic_and_preserves_authoritative_text():
    entries = _fictional_entries()
    original = copy.deepcopy(entries)
    segments = [
        {
            "start": 1.02 * float(item["source_time"]) + 0.20,
            "end": 1.02 * float(item["source_time"]) + 1.0,
            "text": item["text"],
        }
        for item in entries
    ]

    first = align_lyrics(entries, segments)
    second = align_lyrics(copy.deepcopy(entries), copy.deepcopy(segments))
    assert first == second
    assert entries == original
    assert [text for _, text in first["rows"]] == [item["text"] for item in entries]
    assert first["safe"]
    assert first["timing_model"] == "affine"
    assert first["monotonic"]


def test_alignment_does_not_invent_timing_for_unmatched_untimed_lines():
    entries = [
        {"text": "silver morning", "source_time": None},
        {"text": "completely absent phrase", "source_time": None},
    ]
    segments = [{"start": 1.0, "end": 2.0, "text": "silver morning"}]
    result = align_lyrics(entries, segments)
    assert not result["safe"]
    assert not result["complete"]
    assert result["review_count"] >= 1


def test_alignment_requires_real_vocal_evidence():
    with pytest.raises(VerseLatchError):
        align_lyrics([{"text": "line", "source_time": 1.0}], [])


def test_repeated_chorus_is_disambiguated_by_monotonic_sequence_and_source_prior():
    texts = [
        "silver morning",
        "same chorus line",
        "paper horizon",
        "distant lantern",
        "amber window",
        "same chorus line",
        "open water",
        "final lantern",
    ]
    source_times = [1.0, 6.0, 11.0, 16.0, 21.0, 26.0, 31.0, 36.0]
    entries = [
        {"text": text, "source_time": source_time}
        for text, source_time in zip(texts, source_times)
    ]
    expected_times = [value + 0.60 for value in source_times]
    segments = [
        {"start": start, "end": start + 0.75, "text": text}
        for text, start in zip(texts, expected_times)
    ]

    result = align_lyrics(entries, segments)
    actual_times = [start for start, _ in result["rows"]]

    assert result["safe"]
    assert result["review_count"] == 0
    assert [text for _, text in result["rows"]] == texts
    assert actual_times == pytest.approx(expected_times, abs=0.02)
    assert actual_times[1] < actual_times[5]


def test_turkish_unicode_and_apostrophe_variants_can_supply_untimed_evidence():
    entries = [{"text": "İstanbul'da gece", "source_time": None}]
    segments = [{"start": 4.2, "end": 5.0, "text": "istanbulda gece"}]

    result = align_lyrics(entries, segments)

    # A single untimed line cannot make an entire timing model safe, but strong
    # local evidence may give that line a non-invented timestamp for review.
    assert result["complete"]
    assert result["rows"] == [(4.2, "İstanbul'da gece")]
    assert result["review_count"] == 0
    assert not result["safe"]


def test_affine_quality_fixture_has_small_line_start_error_and_preserves_text():
    entries = _fictional_entries()
    expected_times = [1.015 * float(item["source_time"]) + 0.42 for item in entries]
    segments = [
        {"start": start, "end": start + 0.80, "text": item["text"]}
        for item, start in zip(entries, expected_times)
    ]

    result = align_lyrics(entries, segments)
    actual_times = [start for start, _ in result["rows"]]
    errors = sorted(abs(actual - expected) for actual, expected in zip(actual_times, expected_times))
    median_error = errors[len(errors) // 2]
    p95_error = errors[max(0, int(len(errors) * 0.95) - 1)]

    assert result["safe"]
    assert [text for _, text in result["rows"]] == [item["text"] for item in entries]
    assert median_error <= 0.05
    assert p95_error <= 0.10


def test_multiple_lyric_lines_can_map_inside_single_whisper_segment():
    entries = [
        {"text": "silver morning quiet water", "source_time": 1.0},
        {"text": "distant lantern open sky", "source_time": 5.0},
        {"text": "paper horizon winter signal", "source_time": 9.0},
        {"text": "northbound echo amber window", "source_time": 13.0},
    ]
    segments = [
        {
            "start": 1.0,
            "end": 8.0,
            "text": "silver morning quiet water distant lantern open sky",
        },
        {
            "start": 9.0,
            "end": 16.0,
            "text": "paper horizon winter signal northbound echo amber window",
        },
    ]

    result = align_lyrics(entries, segments)

    assert result["complete"]
    assert result["monotonic"]
    assert [text for _, text in result["rows"]] == [item["text"] for item in entries]
    assert [start for start, _ in result["rows"]] == pytest.approx([1.0, 5.0, 9.0, 13.0], abs=0.35)


def test_long_alignment_fixture_remains_complete_and_deterministic():
    entries = []
    segments = []
    pending_text: list[str] = []
    segment_start = 0.0

    for index in range(60):
        line = (
            f"orbit{index} silver{index} quiet{index} "
            f"water{index} lantern{index} sky{index}"
        )
        source_time = index * 3.0
        entries.append({"text": line, "source_time": source_time})

        if index % 2 == 0:
            pending_text = [line]
            segment_start = source_time
        else:
            pending_text.append(line)
            segments.append(
                {
                    "start": segment_start,
                    "end": source_time + 2.5,
                    "text": " ".join(pending_text),
                }
            )

    first = align_lyrics(copy.deepcopy(entries), copy.deepcopy(segments))
    second = align_lyrics(copy.deepcopy(entries), copy.deepcopy(segments))

    assert first == second
    assert first["complete"]
    assert first["monotonic"]
    assert [text for _, text in first["rows"]] == [item["text"] for item in entries]


def test_repeated_chorus_with_missing_and_extra_asr_never_rewrites_text_or_breaks_order():
    entries = [
        {"text": "intro line", "source_time": 1.0},
        {"text": "same chorus", "source_time": 6.0},
        {"text": "middle line", "source_time": 11.0},
        {"text": "same chorus", "source_time": 16.0},
        {"text": "outro line", "source_time": 21.0},
    ]
    segments = [
        {"start": 1.2, "end": 2.0, "text": "intro line"},
        {"start": 6.1, "end": 7.0, "text": "same chorus"},
        {"start": 9.0, "end": 9.5, "text": "hallucinated unrelated words"},
        {"start": 16.2, "end": 17.0, "text": "same chorus"},
        {"start": 21.3, "end": 22.0, "text": "outro line"},
    ]
    first = align_lyrics(copy.deepcopy(entries), copy.deepcopy(segments))
    second = align_lyrics(copy.deepcopy(entries), copy.deepcopy(segments))
    assert first == second
    assert [text for _, text in first["rows"]] == [item["text"] for item in entries]
    starts = [start for start, _ in first["rows"] if start is not None]
    assert starts == sorted(starts)
