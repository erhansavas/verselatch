# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import math

from verselatch_core import validate_asr_segments
from verselatch_core.rhythm import MAX_RHYTHM_EVENTS


_SEGMENT_FIELDS = frozenset(
    {
        "start",
        "end",
        "text",
        "token_confidence",
        "low_confidence_fraction",
        "token_count",
        "words",
    }
)
_WORD_FIELDS = frozenset({"text", "start", "end"})


class WorkerPayloadError(ValueError):
    """A worker success payload violated the typed evidence schema."""


@dataclass(frozen=True)
class WorkerAnalysisPayload:
    segments: tuple[dict[str, object], ...]
    beats: tuple[float, ...]
    onsets: tuple[float, ...]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_segment_schema(raw_segments: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw_segments, list):
        raise WorkerPayloadError("analysis segments must be an array")
    if not raw_segments:
        return ()

    for segment in raw_segments:
        if not isinstance(segment, dict) or not set(segment) <= _SEGMENT_FIELDS:
            raise WorkerPayloadError("invalid analysis segment schema")
        if not _is_number(segment.get("start")) or not _is_number(segment.get("end")):
            raise WorkerPayloadError("analysis segment timestamps must be numbers")
        if not isinstance(segment.get("text"), str):
            raise WorkerPayloadError("analysis segment text must be a string")

        for key in ("token_confidence", "low_confidence_fraction"):
            if key in segment and not _is_number(segment[key]):
                raise WorkerPayloadError(f"analysis segment {key} must be a number")
        if "token_count" in segment and (
            not isinstance(segment["token_count"], int)
            or isinstance(segment["token_count"], bool)
        ):
            raise WorkerPayloadError("analysis segment token_count must be an integer")

        words = segment.get("words")
        if words is not None:
            if not isinstance(words, list):
                raise WorkerPayloadError("analysis segment words must be an array")
            for word in words:
                if not isinstance(word, dict) or set(word) != _WORD_FIELDS:
                    raise WorkerPayloadError("invalid analysis word schema")
                if not isinstance(word.get("text"), str):
                    raise WorkerPayloadError("analysis word text must be a string")
                if not _is_number(word.get("start")) or not _is_number(word.get("end")):
                    raise WorkerPayloadError("analysis word timestamps must be numbers")

    validated = validate_asr_segments(raw_segments)
    if validated is None:
        raise WorkerPayloadError("analysis segments failed domain validation")
    return tuple(validated)


def _validate_rhythm_events(raw: object, *, name: str) -> tuple[float, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_RHYTHM_EVENTS:
        raise WorkerPayloadError(f"invalid {name} array")

    values: list[float] = []
    previous = -1.0
    for item in raw:
        if not _is_number(item):
            raise WorkerPayloadError(f"{name} timestamps must be numbers")
        value = float(item)
        if not math.isfinite(value) or value < 0.0 or value <= previous:
            raise WorkerPayloadError(
                f"{name} timestamps must be finite and strictly increasing"
            )
        values.append(value)
        previous = value
    return tuple(values)


def validate_worker_analysis_payload(raw: object) -> WorkerAnalysisPayload:
    """Return canonical bounded worker evidence or fail closed."""
    if not isinstance(raw, dict) or set(raw) != {"segments", "beats", "onsets"}:
        raise WorkerPayloadError("invalid analysis payload schema")
    return WorkerAnalysisPayload(
        segments=_validate_segment_schema(raw["segments"]),
        beats=_validate_rhythm_events(raw["beats"], name="beat"),
        onsets=_validate_rhythm_events(raw["onsets"], name="onset"),
    )
