# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import math

from verselatch_core import validate_asr_segments
from verselatch_core.rhythm import MAX_RHYTHM_EVENTS


class WorkerPayloadError(ValueError):
    pass


WorkerAnalysisPayload = dict[str, object]


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _segments(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise WorkerPayloadError("analysis segments must be an array")
    if not raw:
        return []

    allowed = {
        "start", "end", "text", "token_confidence",
        "low_confidence_fraction", "token_count", "words",
    }
    word_fields = {"text", "start", "end"}
    for segment in raw:
        if not isinstance(segment, dict) or not set(segment) <= allowed:
            raise WorkerPayloadError("invalid analysis segment schema")
        if not _number(segment.get("start")) or not _number(segment.get("end")):
            raise WorkerPayloadError("analysis segment timestamps must be numbers")
        if not isinstance(segment.get("text"), str):
            raise WorkerPayloadError("analysis segment text must be a string")
        for key in ("token_confidence", "low_confidence_fraction"):
            if key in segment and not _number(segment[key]):
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
                if not isinstance(word, dict) or set(word) != word_fields:
                    raise WorkerPayloadError("invalid analysis word schema")
                if not isinstance(word.get("text"), str):
                    raise WorkerPayloadError("analysis word text must be a string")
                if not _number(word.get("start")) or not _number(word.get("end")):
                    raise WorkerPayloadError("analysis word timestamps must be numbers")

    validated = validate_asr_segments(raw)
    if validated is None:
        raise WorkerPayloadError("analysis segments failed domain validation")
    return validated


def _events(raw: object, name: str) -> list[float]:
    if not isinstance(raw, list) or len(raw) > MAX_RHYTHM_EVENTS:
        raise WorkerPayloadError(f"invalid {name} array")
    result: list[float] = []
    previous = -1.0
    for item in raw:
        if not _number(item):
            raise WorkerPayloadError(f"{name} timestamps must be numbers")
        value = float(item)
        if not math.isfinite(value) or value < 0.0 or value <= previous:
            raise WorkerPayloadError(f"{name} timestamps must be finite and strictly increasing")
        result.append(value)
        previous = value
    return result


def validate_worker_analysis_payload(raw: object) -> WorkerAnalysisPayload:
    if not isinstance(raw, dict) or set(raw) != {"segments", "rhythm"}:
        raise WorkerPayloadError("invalid analysis payload schema")
    rhythm = raw["rhythm"]
    if not isinstance(rhythm, dict):
        raise WorkerPayloadError("analysis rhythm must be an object")
    keys = set(rhythm)
    if keys not in (set(), {"beats", "onsets"}):
        raise WorkerPayloadError("invalid analysis rhythm schema")
    canonical_rhythm: dict[str, object] = {}
    if rhythm:
        canonical_rhythm = {
            "beats": _events(rhythm["beats"], "beat"),
            "onsets": _events(rhythm["onsets"], "onset"),
        }
    return {"segments": _segments(raw["segments"]), "rhythm": canonical_rhythm}
