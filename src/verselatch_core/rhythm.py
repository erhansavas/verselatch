# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import math
import statistics

MAX_RHYTHM_EVENTS = 20_000


def parse_aubio_times(text: str, *, maximum_events: int = MAX_RHYTHM_EVENTS) -> list[float]:
    """Parse strictly increasing finite non-negative aubio event timestamps."""
    values: list[float] = []

    for raw_line in text.splitlines():
        token = raw_line.strip().split(maxsplit=1)
        if not token:
            continue

        try:
            value = float(token[0])
        except ValueError:
            continue

        if not math.isfinite(value) or value < 0.0:
            continue
        if values and value <= values[-1]:
            # Duplicate or backward evidence is ignored rather than repaired.
            continue

        values.append(value)
        if len(values) >= maximum_events:
            break

    return values


def summarize_rhythm(beats: list[float], onsets: list[float]) -> dict[str, object]:
    """Return conservative rhythm descriptors; never infer lyric boundaries."""
    intervals = [
        right - left
        for left, right in zip(beats, beats[1:])
        if 0.20 <= (right - left) <= 2.50
    ]

    bpm: float | None = None
    regularity = "unresolved"
    variation: float | None = None

    if len(intervals) >= 3:
        median_interval = statistics.median(intervals)
        if median_interval > 0:
            bpm = 60.0 / median_interval
            deviations = [abs(value - median_interval) for value in intervals]
            variation = statistics.median(deviations) / median_interval
            if variation <= 0.04:
                regularity = "steady"
            elif variation <= 0.10:
                regularity = "moderately variable"
            else:
                regularity = "variable"

    duration_hint = 0.0
    if beats:
        duration_hint = max(duration_hint, beats[-1])
    if onsets:
        duration_hint = max(duration_hint, onsets[-1])

    onset_rate: float | None = None
    if duration_hint > 1.0:
        onset_rate = len(onsets) / duration_hint

    return {
        "bpm": bpm,
        "beats": len(beats),
        "onsets": len(onsets),
        "regularity": regularity,
        "variation": variation,
        "onset_rate": onset_rate,
    }


def rhythm_report_lines(profile: dict[str, object] | None) -> list[str]:
    """Format rhythm evidence for diagnostics without turning it into a timing rule."""
    if not profile:
        return ["RHYTHM        unavailable"]

    bpm = profile.get("bpm")
    bpm_text = (
        f"{bpm:.1f} BPM"
        if isinstance(bpm, (int, float)) and math.isfinite(float(bpm))
        else "unresolved"
    )

    onset_rate = profile.get("onset_rate")
    onset_text = (
        f"{float(onset_rate):.2f}/s"
        if isinstance(onset_rate, (int, float)) and math.isfinite(float(onset_rate))
        else "unresolved"
    )

    return [
        "RHYTHM        aubio local analysis",
        "TEMPO         " + bpm_text,
        "PULSE         " + str(profile.get("regularity", "unresolved")),
        "BEATS         " + str(profile.get("beats", 0)),
        "TRANSIENTS    " + str(profile.get("onsets", 0)) + " · " + onset_text,
    ]
