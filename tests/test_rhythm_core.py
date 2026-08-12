# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import math

from verselatch_core.rhythm import parse_aubio_times, rhythm_report_lines, summarize_rhythm


def test_aubio_parser_is_finite_nonnegative_monotonic_and_bounded():
    text = "\n".join(
        [
            "nan",
            "-1.0",
            "0.50 extra",
            "0.50 duplicate",
            "0.49 backwards",
            "1.00",
            "inf",
            "2.00",
        ]
    )
    assert parse_aubio_times(text) == [0.5, 1.0, 2.0]
    assert parse_aubio_times("\n".join(str(i / 10) for i in range(100)), maximum_events=7) == [
        0.0,
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.6,
    ]


def test_rhythm_profile_is_diagnostic_only_and_stable():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    onsets = [0.15, 0.48, 0.95, 1.42, 1.90, 2.30]
    profile = summarize_rhythm(beats, onsets)

    assert math.isclose(float(profile["bpm"]), 120.0, abs_tol=0.01)
    assert profile["regularity"] == "steady"
    lines = rhythm_report_lines(profile)
    assert "TEMPO         120.0 BPM" in lines
    assert not any("snap" in line.casefold() or "lyric boundary" in line.casefold() for line in lines)
