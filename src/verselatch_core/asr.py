# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from collections import Counter
import math
import re
import statistics
import zlib

from .constants import MAX_ASR_SEGMENTS, MAX_ASR_TEXT_CHARS
from .lrc import ASR_WORD_RE, normalize

STAGE_CUE_RE = re.compile(r"^\s*[\[\(\{<].{1,160}[\]\)\}>]\s*$", re.DOTALL)
MUSIC_SYMBOL_RE = re.compile(r"^[\s♪♫♬♩♭♯•·…._-]+$")
MULTILINGUAL_NON_LYRIC_CUES = {
    "music", "music playing", "instrumental", "instrumental music",
    "applause", "clapping", "laughter", "silence", "background music",
    "müzik", "müzik çalıyor", "enstrümantal", "alkış", "kahkaha", "sessizlik",
    "musique", "música", "musik",
}

def validate_asr_segments(
    raw_segments,
) -> list[dict] | None:
    if (
        not isinstance(raw_segments, list)
        or not raw_segments
        or len(raw_segments) > MAX_ASR_SEGMENTS
    ):
        return None

    validated: list[dict] = []
    previous_start = -1.0

    for item in raw_segments:
        if not isinstance(item, dict):
            return None

        text = item.get("text")

        if not isinstance(text, str):
            return None

        text = " ".join(text.split())

        if (
            not text
            or len(text) > MAX_ASR_TEXT_CHARS
        ):
            return None

        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError, OverflowError):
            return None

        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0.0
            or end < start
            or start < previous_start
        ):
            return None

        previous_start = start

        validated_item = {
            "start": start,
            "end": end,
            "text": text,
        }

        # Full whisper.cpp JSON exposes token probabilities. Preserve only
        # bounded, finite summary values in the local cache; raw token arrays
        # are unnecessary after parsing and would inflate cache size.
        token_confidence = item.get("token_confidence")
        low_confidence_fraction = item.get("low_confidence_fraction")
        token_count = item.get("token_count")

        if token_confidence is not None:
            try:
                value = float(token_confidence)
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                return None
            validated_item["token_confidence"] = value

        if low_confidence_fraction is not None:
            try:
                value = float(low_confidence_fraction)
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                return None
            validated_item["low_confidence_fraction"] = value

        if token_count is not None:
            if isinstance(token_count, bool):
                return None
            try:
                value = int(token_count)
            except (TypeError, ValueError, OverflowError):
                return None
            if value < 0 or value > 10000:
                return None
            validated_item["token_count"] = value

        raw_words = item.get("words")
        if raw_words is not None:
            if not isinstance(raw_words, list) or len(raw_words) > 128:
                return None

            validated_words: list[dict] = []
            previous_word_start = -1.0
            for raw_word in raw_words:
                if not isinstance(raw_word, dict):
                    return None

                word_text = raw_word.get("text")
                if (
                    not isinstance(word_text, str)
                    or not word_text
                    or len(word_text) > 128
                    or ASR_WORD_RE.fullmatch(word_text) is None
                ):
                    return None

                try:
                    word_start = float(raw_word.get("start"))
                    word_end = float(raw_word.get("end"))
                except (TypeError, ValueError, OverflowError):
                    return None

                if (
                    not math.isfinite(word_start)
                    or not math.isfinite(word_end)
                    or word_start < max(0.0, start - 0.5)
                    or word_end < word_start
                    or word_end > end + 0.5
                    or word_start < previous_word_start
                ):
                    return None

                previous_word_start = word_start
                validated_words.append(
                    {
                        "text": word_text,
                        "start": word_start,
                        "end": word_end,
                    }
                )

            if validated_words:
                validated_item["words"] = validated_words

        validated.append(validated_item)

    return validated

def _parse_timestamp_text_optional(value: str) -> float | None:
    """Parse whisper.cpp HH:MM:SS.mmm text without conflating invalid input with zero."""
    match = re.fullmatch(
        r"(\d+):(\d+):(\d+)[,.](\d+)",
        value.strip(),
    )
    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    if minutes >= 60 or seconds >= 60:
        return None

    fraction_raw = match.group(4)
    fraction = int(fraction_raw) / (10 ** len(fraction_raw))
    value_seconds = hours * 3600 + minutes * 60 + seconds + fraction
    return value_seconds if math.isfinite(value_seconds) else None


def parse_timestamp_text(value: str) -> float:
    """Backward-compatible timestamp parser used by diagnostics/tests."""
    parsed = _parse_timestamp_text_optional(value)
    return 0.0 if parsed is None else parsed

def parse_whisper_json(
    data: dict,
) -> list[dict]:
    segments: list[dict] = []

    raw_segments = data.get(
        "transcription",
        [],
    )

    if not isinstance(
        raw_segments,
        list,
    ):
        return []

    for item in raw_segments:
        if not isinstance(
            item,
            dict,
        ):
            continue

        raw_text = item.get(
            "text",
            "",
        )

        if not isinstance(
            raw_text,
            str,
        ):
            continue

        text = " ".join(
            raw_text.split()
        )

        if not text:
            continue

        if len(text) > MAX_ASR_TEXT_CHARS:
            text = text[:MAX_ASR_TEXT_CHARS]

        offsets = item.get(
            "offsets",
            {},
        )

        timestamps = item.get(
            "timestamps",
            {},
        )

        start = 0.0
        end = 0.0
        offsets_valid = False

        if isinstance(
            offsets,
            dict,
        ):
            try:
                candidate_start = float(
                    offsets.get(
                        "from",
                        0,
                    )
                ) / 1000.0

                candidate_end = float(
                    offsets.get(
                        "to",
                        0,
                    )
                ) / 1000.0

                if (
                    math.isfinite(candidate_start)
                    and math.isfinite(candidate_end)
                    and candidate_start >= 0.0
                    and candidate_end >= candidate_start
                ):
                    start = candidate_start
                    end = candidate_end
                    offsets_valid = True

            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                pass

        if not offsets_valid:
            if not isinstance(timestamps, dict):
                continue
            parsed_start = _parse_timestamp_text_optional(str(timestamps.get("from", "")))
            parsed_end = _parse_timestamp_text_optional(str(timestamps.get("to", "")))
            if parsed_start is None or parsed_end is None or parsed_end < parsed_start:
                continue
            start = parsed_start
            end = parsed_end

        parsed = {
            "start": max(0.0, start),
            "end": max(start, end),
            "text": text,
        }

        # `-ojf` exposes probability and, when whisper.cpp produced them,
        # per-token offsets. Preserve a compact word-timing view for alignment.
        # The editable lyrics remain authoritative; these timings are evidence.
        raw_tokens = item.get("tokens")
        probabilities: list[float] = []
        token_stream = ""
        token_spans: list[dict] = []

        if isinstance(raw_tokens, list):
            for token in raw_tokens:
                if not isinstance(token, dict):
                    continue

                token_text = token.get("text")
                if not isinstance(token_text, str):
                    continue

                stripped_token = token_text.strip()
                is_special = (
                    not stripped_token
                    or (
                        stripped_token.startswith("<|")
                        and stripped_token.endswith("|>")
                    )
                    or re.fullmatch(r"\[_[A-Z0-9_]+_\]", stripped_token)
                    is not None
                )
                if is_special:
                    continue

                char_start = len(token_stream)
                token_stream += token_text
                char_end = len(token_stream)

                token_start: float | None = None
                token_end: float | None = None
                token_offsets = token.get("offsets")
                if isinstance(token_offsets, dict):
                    try:
                        candidate_start = float(token_offsets.get("from")) / 1000.0
                        candidate_end = float(token_offsets.get("to")) / 1000.0
                        if (
                            math.isfinite(candidate_start)
                            and math.isfinite(candidate_end)
                            and candidate_start >= 0.0
                            and candidate_end >= candidate_start
                        ):
                            token_start = candidate_start
                            token_end = candidate_end
                    except (TypeError, ValueError, OverflowError):
                        pass

                token_spans.append(
                    {
                        "char_start": char_start,
                        "char_end": char_end,
                        "start": token_start,
                        "end": token_end,
                    }
                )

                try:
                    probability = float(token.get("p"))
                except (TypeError, ValueError, OverflowError):
                    continue

                if math.isfinite(probability) and 0.0 <= probability <= 1.0:
                    probabilities.append(probability)

        if probabilities:
            parsed["token_confidence"] = statistics.fmean(probabilities)
            parsed["low_confidence_fraction"] = (
                sum(value < 0.20 for value in probabilities)
                / len(probabilities)
            )
            parsed["token_count"] = len(probabilities)

        raw_word_matches = list(ASR_WORD_RE.finditer(token_stream))
        timed_words: list[dict] = []
        for word_match in raw_word_matches:
            overlapping = [
                token
                for token in token_spans
                if token["char_end"] > word_match.start()
                and token["char_start"] < word_match.end()
                and token["start"] is not None
                and token["end"] is not None
            ]
            if not overlapping:
                continue

            word_start = min(float(token["start"]) for token in overlapping)
            word_end = max(float(token["end"]) for token in overlapping)
            if word_end < word_start:
                continue

            timed_words.append(
                {
                    "text": word_match.group(0),
                    "start": word_start,
                    "end": word_end,
                }
            )

        # Avoid mixing sparse token timestamps with interpolated words. Use
        # native word evidence only when most decoded words received timing.
        if raw_word_matches and len(timed_words) >= math.ceil(len(raw_word_matches) * 0.75):
            parsed["words"] = timed_words

        segments.append(parsed)

        if len(segments) >= MAX_ASR_SEGMENTS:
            break

    return validate_asr_segments(segments) or []

def is_non_lyric_asr_text(
    text: str,
) -> bool:
    """Reject stage directions/non-speech captions, not ordinary lyric text."""
    stripped = " ".join((text or "").split()).strip()

    if not stripped:
        return True

    if MUSIC_SYMBOL_RE.fullmatch(stripped):
        return True

    if STAGE_CUE_RE.fullmatch(stripped):
        return True

    normalized = normalize(stripped)

    if not normalized:
        return True

    if normalized in MULTILINGUAL_NON_LYRIC_CUES:
        return True

    return False

def sanitize_generated_segments(
    segments: list[dict],
) -> tuple[list[dict], int]:
    """Keep only plausible sung/spoken text for an unverified draft.

    This intentionally does not try to name instruments or sound effects.
    Whisper's non-speech-token suppression is the primary decode-time filter;
    this is a final fail-closed guard against captions such as '[music]'.
    """
    clean: list[dict] = []
    dropped = 0

    for segment in segments:
        text = str(segment.get("text", ""))

        if is_non_lyric_asr_text(text):
            dropped += 1
            continue

        clean.append(segment)

    return clean, dropped

def generated_word_tokens(text: str) -> list[str]:
    return [
        match.group(0).casefold()
        for match in ASR_WORD_RE.finditer(text or "")
    ]

def repetition_profile(text: str) -> dict:
    words = generated_word_tokens(text)
    total = len(words)
    best_count = 0
    best_coverage = 0.0
    best_n = 0

    for n in range(2, 6):
        if total < n:
            continue

        grams = [
            tuple(words[index:index + n])
            for index in range(total - n + 1)
        ]
        counts = Counter(grams)
        repeated = {
            gram
            for gram, count in counts.items()
            if count >= 3
        }
        if not repeated:
            continue

        covered = [False] * total
        local_max = 0
        for index, gram in enumerate(grams):
            if gram not in repeated:
                continue
            local_max = max(local_max, counts[gram])
            for covered_index in range(index, min(total, index + n)):
                covered[covered_index] = True

        coverage = sum(covered) / total if total else 0.0
        if (coverage, local_max, n) > (best_coverage, best_count, best_n):
            best_coverage = coverage
            best_count = local_max
            best_n = n

    raw = (text or "").encode("utf-8", errors="ignore")
    compression_ratio = 1.0
    if len(raw) >= 48:
        compressed = zlib.compress(raw, level=6)
        if compressed:
            compression_ratio = len(raw) / len(compressed)

    return {
        "words": total,
        "repeat_count": best_count,
        "repeat_coverage": best_coverage,
        "repeat_ngram": best_n,
        "compression_ratio": compression_ratio,
    }

def obvious_generation_hallucination_reason(segment: dict) -> str | None:
    text = str(segment.get("text", ""))
    profile = repetition_profile(text)
    words = int(profile["words"])

    if len(text) > 900 or words > 120:
        return "runaway segment length"

    if (
        words >= 18
        and profile["repeat_count"] >= 4
        and profile["repeat_coverage"] >= 0.68
    ):
        return "runaway phrase repetition"

    if (
        words >= 24
        and profile["compression_ratio"] >= 2.60
        and profile["repeat_count"] >= 3
    ):
        return "highly repetitive decoder output"

    return None

def assess_generated_draft(segments: list[dict]) -> dict:
    """Fail closed on obvious Whisper hallucination/repetition.

    This is deliberately not a spell-checker. A language model or dictionary
    must never silently invent lyric words that are not supported by audio.
    """
    severe: list[dict] = []
    confidences: list[tuple[float, int]] = []
    low_probability_tokens = 0.0
    probability_tokens = 0
    total_words = 0

    for index, segment in enumerate(segments):
        text = str(segment.get("text", ""))
        total_words += len(generated_word_tokens(text))

        reason = obvious_generation_hallucination_reason(segment)
        if reason is not None:
            severe.append({
                "index": index,
                "reason": reason,
            })

        confidence = segment.get("token_confidence")
        count = segment.get("token_count")
        low_fraction = segment.get("low_confidence_fraction")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(float(confidence))
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
        ):
            confidences.append((float(confidence), count))
            probability_tokens += count
            if (
                isinstance(low_fraction, (int, float))
                and not isinstance(low_fraction, bool)
                and math.isfinite(float(low_fraction))
            ):
                low_probability_tokens += max(0.0, min(1.0, float(low_fraction))) * count

    weighted_confidence = None
    low_probability_fraction = None
    if probability_tokens > 0:
        weighted_confidence = (
            sum(value * count for value, count in confidences)
            / probability_tokens
        )
        low_probability_fraction = low_probability_tokens / probability_tokens

    # Token probability is supporting evidence, not a calibrated word-accuracy
    # score. For generated lyrics we fail closed when this evidence is absent or
    # clearly weak. `-ojf` is a required CLI capability in the installer, so a
    # missing probability stream is treated as a quality failure rather than an
    # excuse to export unverified text.
    confidence_missing = probability_tokens < 3
    confidence_failure = bool(
        confidence_missing
        or weighted_confidence is None
        or weighted_confidence < 0.30
        or low_probability_fraction is None
        or low_probability_fraction > 0.60
    )

    safe = bool(
        segments
        and total_words >= 3
        and not severe
        and not confidence_failure
    )

    return {
        "safe": safe,
        "severe": severe,
        "severe_count": len(severe),
        "total_words": total_words,
        "weighted_confidence": weighted_confidence,
        "low_probability_fraction": low_probability_fraction,
        "probability_tokens": probability_tokens,
        "confidence_missing": confidence_missing,
        "confidence_failure": confidence_failure,
    }
