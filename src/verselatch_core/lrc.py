# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import math
import re
import unicodedata

from .constants import MAX_LYRIC_LINES, MAX_LYRICS_BYTES
from .errors import VerseLatchError

LRC_TIME_RE = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]")
LRC_CAPTURE_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
ENHANCED_TIME_RE = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
ASR_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)

def normalize(text: str) -> str:
    """Normalize lyric/ASR text for matching without altering displayed text.

    Matching is deliberately accent-insensitive and folds Turkish dotted/dotless
    I to a common form. This prevents Unicode combining marks (for example the
    case-folded form of ``İ``) from accidentally splitting a word. The original
    lyric text is never rewritten with this representation.
    """
    folded = unicodedata.normalize(
        "NFKD",
        unicodedata.normalize("NFKC", text or "").casefold(),
    )

    result: list[str] = []
    previous_space = False

    for char in folded:
        if unicodedata.category(char).startswith("M"):
            # Accent/combining marks are irrelevant to timing evidence.
            continue

        if char == "ı":
            char = "i"

        if char.isalnum():
            result.append(char)
            previous_space = False
            continue

        if char in {"'", "’"}:
            continue

        if not previous_space and result:
            result.append(" ")
            previous_space = True

    return "".join(result).strip()

def _capture_lrc_seconds(match: re.Match) -> float:
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction_raw = match.group(3) or ""

    if seconds >= 60:
        raise ValueError("Invalid LRC seconds field.")

    fraction = (
        int(fraction_raw) / (10 ** len(fraction_raw))
        if fraction_raw
        else 0.0
    )

    return minutes * 60.0 + seconds + fraction

def parse_lyric_document(
    content: str,
) -> dict:
    """Parse lyric text while preserving source LRC timestamps.

    Metadata tags and empty end markers are not lyric rows. Multiple LRC
    timestamps on one textual line are supported. Untimed TXT/plain-LRC lines
    remain explicit with ``source_time=None`` rather than receiving fabricated
    timing.
    """
    entries: list[dict] = []
    for raw in content.splitlines():
        line = raw.replace("\ufeff", "").strip()

        if not line:
            continue

        stamps = list(LRC_CAPTURE_RE.finditer(line))
        lyric = LRC_TIME_RE.sub("", line)
        lyric = ENHANCED_TIME_RE.sub("", lyric).strip()

        if not lyric:
            # Timestamp-only end markers are not lyric rows.
            continue

        if (
            not stamps
            and lyric.startswith("[")
            and lyric.endswith("]")
            and ":" in lyric
        ):
            # LRC metadata such as [ar:], [ti:], [al:], [length:].
            continue

        if len(lyric) > 1000:
            lyric = lyric[:1000]

        if stamps:
            for stamp in stamps:
                try:
                    source_time = _capture_lrc_seconds(stamp)
                except (TypeError, ValueError, OverflowError):
                    continue

                entries.append(
                    {
                        "text": lyric,
                        "source_time": source_time,
                    }
                )

                if len(entries) >= MAX_LYRIC_LINES:
                    break
        else:
            entries.append(
                {
                    "text": lyric,
                    "source_time": None,
                }
            )

        if len(entries) >= MAX_LYRIC_LINES:
            break

    return {
        "entries": entries,
    }

def timing_pattern_is_suspicious(
    entries: list[dict],
) -> bool:
    """Detect the legacy equal-fraction interpolation fingerprint.

    A legitimate coarse LRC can reasonably use whole-second (.00) timing, so
    that case is deliberately not rejected. The suspicious pattern requires a
    dominant *non-zero* centisecond fraction and mostly integer inter-line
    gaps, which is what the old VerseLatch interpolation bug produced.
    """
    times = [
        float(item["source_time"])
        for item in entries
        if item.get("source_time") is not None
    ]

    if len(times) < 10:
        return False

    if any(
        not math.isfinite(value) or value < 0.0
        for value in times
    ):
        return True

    if any(
        right <= left
        for left, right in zip(times, times[1:])
    ):
        return True

    fractions = [
        int(round(value * 100.0)) % 100
        for value in times
    ]

    counts: dict[int, int] = {}
    for fraction in fractions:
        counts[fraction] = counts.get(fraction, 0) + 1

    dominant_fraction, dominant_count = max(
        counts.items(),
        key=lambda item: item[1],
    )

    dominant_ratio = dominant_count / len(fractions)

    gaps = [
        right - left
        for left, right in zip(times, times[1:])
    ]

    integer_gap_ratio = (
        sum(
            abs(gap - round(gap)) <= 0.025
            for gap in gaps
        )
        / len(gaps)
        if gaps
        else 0.0
    )

    return (
        dominant_fraction != 0
        and dominant_ratio >= 0.80
        and integer_gap_ratio >= 0.70
    )

def same_lyric_text(
    first: list[dict],
    second: list[dict],
) -> bool:
    if len(first) != len(second):
        return False

    return all(
        normalize(left.get("text", ""))
        == normalize(right.get("text", ""))
        for left, right in zip(first, second)
    )

def timestamp(
    seconds: float,
) -> str:
    centiseconds = max(
        0,
        round(
            seconds * 100
        ),
    )

    minutes = (
        centiseconds
        // 6000
    )

    remainder = (
        centiseconds
        % 6000
    )

    secs = (
        remainder
        // 100
    )

    cs = (
        remainder
        % 100
    )

    return (
        f"[{minutes:02d}:"
        f"{secs:02d}."
        f"{cs:02d}]"
    )

def render_lrc(
    rows: list[tuple[float, str]],
) -> str:
    return "".join(
        f"{timestamp(start)}{text}\n"
        for start, text
        in rows
    )

def parse_reviewed_lrc(
    text: str,
) -> list[tuple[float, str]]:
    """Validate the editable preview before any user-approved save."""
    if len(text.encode("utf-8")) > MAX_LYRICS_BYTES:
        raise VerseLatchError("Reviewed LRC exceeds the safety size limit.")

    rows: list[tuple[float, str]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = LRC_CAPTURE_RE.match(line)
        if match is None or match.start() != 0:
            raise VerseLatchError(
                "Every non-empty preview line must start with one LRC timestamp."
            )

        lyric = line[match.end():].strip()
        if not lyric or LRC_TIME_RE.search(lyric):
            raise VerseLatchError(
                "Each preview line must contain exactly one timestamp and lyric text."
            )

        try:
            start = _capture_lrc_seconds(match)
        except ValueError as exc:
            raise VerseLatchError("Preview contains an invalid LRC timestamp.") from exc

        rows.append((start, lyric))
        if len(rows) > MAX_LYRIC_LINES:
            raise VerseLatchError("Reviewed LRC contains too many lyric lines.")

    if not rows:
        raise VerseLatchError("Reviewed LRC contains no timed lyric lines.")

    if any(
        right[0] <= left[0]
        for left, right in zip(rows, rows[1:])
    ):
        raise VerseLatchError(
            "Reviewed LRC timestamps must be strictly increasing."
        )

    return rows
