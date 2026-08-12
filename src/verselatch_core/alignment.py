# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from bisect import bisect_left
from difflib import SequenceMatcher
import math
import statistics

from .errors import VerseLatchError
from .lrc import ASR_WORD_RE, normalize, timing_pattern_is_suspicious

def _timed_words_for_segments(
    segments: list[dict],
) -> list[dict]:
    """Return word evidence, preferring whisper.cpp token-derived timing.

    `--max-len` plus `--split-on-word` asks whisper.cpp for short word-aware
    segments. Full JSON may also carry token offsets; when the parser retained
    sufficiently complete native word timing, use it directly. Otherwise the
    fallback interpolates only inside the already-bounded segment envelope.
    """
    words: list[dict] = []

    for segment in segments:
        native_words = segment.get("words")
        if isinstance(native_words, list) and native_words:
            for item in native_words:
                display_text = str(item["text"])
                token = normalize(display_text).replace(" ", "")
                if not token:
                    continue
                words.append(
                    {
                        "token": token,
                        "text": display_text,
                        "start": float(item["start"]),
                        "end": float(item["end"]),
                        "timing": "native",
                    }
                )
            continue

        text = str(segment.get("text", ""))
        matches = list(ASR_WORD_RE.finditer(text))
        if not matches:
            continue

        start = float(segment["start"])
        end = max(start, float(segment["end"]))
        duration = max(0.0, end - start)
        count = len(matches)

        for index, match in enumerate(matches):
            word_start = start + duration * index / count
            word_end = start + duration * (index + 1) / count
            display_text = match.group(0)
            token = normalize(display_text).replace(" ", "")
            if not token:
                continue
            words.append(
                {
                    "token": token,
                    "text": display_text,
                    "start": word_start,
                    "end": word_end,
                    "timing": "segment-fallback",
                }
            )

    return words

def _candidate_word_windows(
    expected: str,
    timed_words: list[dict],
    token_positions: dict[str, list[int]],
    word_starts: list[float],
    window_text_cache: dict[tuple[int, int], tuple[str, str]],
    source_time: float | None,
    *,
    limit: int = 14,
) -> list[dict]:
    """Return a small set of plausible contiguous ASR word windows.

    A full O(lines * words * widths) scan becomes unnecessarily expensive on
    long songs. Seed candidate starts from the rarest lyric tokens, then add a
    bounded source-time neighbourhood when an LRC prior exists. The monotonic
    beam in `_map_lyrics_to_segments` still makes the final sequence decision.
    """
    expected_words = [
        token
        for match in ASR_WORD_RE.finditer(expected or "")
        if (token := normalize(match.group(0)).replace(" ", ""))
    ]
    if not expected_words or not timed_words:
        return []

    word_count = len(timed_words)
    expected_normalized = " ".join(expected_words)
    target_count = len(expected_words)
    minimum = max(1, target_count - 2)
    maximum = min(word_count, target_count + 4)
    if minimum > maximum:
        return []

    expected_occurrences: dict[str, list[int]] = {}
    for expected_index, token in enumerate(expected_words):
        expected_occurrences.setdefault(token, []).append(expected_index)

    available_tokens = sorted(
        (
            len(token_positions[token]),
            token,
        )
        for token in expected_occurrences
        if token in token_positions
    )

    lexical_votes: dict[int, int] = {}
    for _, token in available_tokens[:3]:
        asr_positions = token_positions[token]
        for expected_index in expected_occurrences[token]:
            for asr_index in asr_positions:
                base = asr_index - expected_index
                for delta, weight in ((0, 3), (-1, 2), (1, 2), (-2, 1), (2, 1)):
                    offset = base + delta
                    if 0 <= offset < word_count:
                        lexical_votes[offset] = (
                            lexical_votes.get(offset, 0) + weight
                        )

    source_index: int | None = None
    time_starts: set[int] = set()
    if source_time is not None and word_starts:
        source_index = bisect_left(word_starts, source_time)
        source_index = min(max(source_index, 0), word_count - 1)
        local_radius = 16
        lower = max(0, source_index - local_radius)
        upper = min(word_count, source_index + local_radius + 1)
        time_starts.update(range(lower, upper))

    # Bound pathological repetition deterministically. Starts supported by
    # multiple expected tokens win; source time resolves otherwise-equal chorus
    # repetitions without becoming the sole source of truth.
    lexical_limit = 128 if source_index is not None else 192
    ranked_lexical = sorted(
        lexical_votes,
        key=lambda value: (
            -lexical_votes[value],
            (
                abs(value - source_index)
                if source_index is not None
                else value
            ),
            value,
        ),
    )[:lexical_limit]

    starts = set(ranked_lexical) | time_starts
    if not starts:
        return []

    candidates: list[dict] = []
    for offset in sorted(starts):
        for width in range(minimum, maximum + 1):
            word_end = offset + width
            if word_end > word_count:
                break

            cache_key = (offset, word_end)
            cached_text = window_text_cache.get(cache_key)
            if cached_text is None:
                window = timed_words[offset:word_end]
                cached_text = (
                    " ".join(str(item["token"]) for item in window),
                    " ".join(str(item["text"]) for item in window),
                )
                window_text_cache[cache_key] = cached_text
            candidate_text, evidence_text = cached_text

            if candidate_text == expected_normalized:
                score = 1.0
            else:
                score = SequenceMatcher(
                    None,
                    expected_normalized,
                    candidate_text,
                ).ratio()
            if score < 0.26:
                continue

            timing_penalty = 0.0
            if source_time is not None:
                distance = abs(
                    float(timed_words[offset]["start"]) - source_time
                )
                timing_penalty = min(distance / 60.0, 1.0) * 0.14

            tightness_penalty = abs(width - target_count) * 0.002
            ranking = score - timing_penalty - tightness_penalty
            candidates.append(
                {
                    "score": score,
                    "ranking": ranking,
                    "word_start": offset,
                    "word_end": word_end,
                    "start": float(timed_words[offset]["start"]),
                    "end": float(timed_words[word_end - 1]["end"]),
                    "evidence": evidence_text,
                }
            )

    candidates.sort(
        key=lambda item: (
            float(item["ranking"]),
            float(item["score"]),
            -int(item["word_start"]),
        ),
        reverse=True,
    )
    return candidates[:limit]

def _map_lyrics_to_segments(
    entries: list[dict],
    segments: list[dict],
) -> list[dict | None]:
    """Monotonic lyric matching over timed ASR words with a bounded beam.

    Multiple lyric lines may legitimately live inside one Whisper segment. A
    word-level beam avoids the old one-line-per-segment assumption while a
    broad source-time prior disambiguates repeated choruses.
    """
    timed_words = _timed_words_for_segments(segments)
    if not timed_words:
        return [None] * len(entries)

    token_positions: dict[str, list[int]] = {}
    word_starts: list[float] = []
    for index, item in enumerate(timed_words):
        token_positions.setdefault(str(item["token"]), []).append(index)
        word_starts.append(float(item["start"]))

    window_text_cache: dict[tuple[int, int], tuple[str, str]] = {}

    candidate_sets = [
        _candidate_word_windows(
            str(entry["text"]),
            timed_words,
            token_positions,
            word_starts,
            window_text_cache,
            (
                float(entry["source_time"])
                if entry.get("source_time") is not None
                else None
            ),
        )
        for entry in entries
    ]

    # (score, next free word index, mapped history)
    beam: list[tuple[float, int, tuple[dict | None, ...]]] = [
        (0.0, 0, ())
    ]
    beam_width = 40

    for candidates in candidate_sets:
        expanded: list[tuple[float, int, tuple[dict | None, ...]]] = []

        for total_score, cursor, history in beam:
            expanded.append(
                (
                    total_score - 0.28,
                    cursor,
                    history + (None,),
                )
            )

            for candidate in candidates:
                word_start = int(candidate["word_start"])
                word_end = int(candidate["word_end"])
                if word_start < cursor:
                    continue

                gap = word_start - cursor
                gap_penalty = min(gap / 40.0, 1.0) * 0.06
                gain = (
                    (float(candidate["score"]) - 0.35) * 1.9
                    - gap_penalty
                )
                expanded.append(
                    (
                        total_score + gain,
                        word_end,
                        history + (candidate,),
                    )
                )

        # Collapse states that end at the same cursor, then retain a small
        # deterministic beam. This bounds memory/time even on long recordings.
        best_by_cursor: dict[int, tuple[float, int, tuple[dict | None, ...]]] = {}
        for state in expanded:
            cursor = state[1]
            previous = best_by_cursor.get(cursor)
            if previous is None or state[0] > previous[0]:
                best_by_cursor[cursor] = state

        beam = sorted(
            best_by_cursor.values(),
            key=lambda state: (state[0], -state[1]),
            reverse=True,
        )[:beam_width]

    if not beam:
        return [None] * len(entries)

    _, _, history = max(beam, key=lambda state: state[0])
    mapped: list[dict | None] = []
    for item in history:
        if item is None:
            mapped.append(None)
        else:
            mapped.append(
                {
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                    "score": float(item["score"]),
                    "evidence": str(item["evidence"]),
                }
            )

    return mapped

def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return ordered[max(0, min(index, len(ordered) - 1))]

def _weighted_linear_fit(
    anchors: list[dict],
) -> tuple[float, float] | None:
    if len(anchors) < 2:
        return None

    weights = [
        max(0.10, float(item.get("score", 0.0)) ** 2)
        for item in anchors
    ]
    total_weight = sum(weights)
    if total_weight <= 0.0:
        return None

    mean_x = sum(
        weight * float(item["source"])
        for weight, item in zip(weights, anchors)
    ) / total_weight
    mean_y = sum(
        weight * float(item["asr"])
        for weight, item in zip(weights, anchors)
    ) / total_weight

    denominator = sum(
        weight * (float(item["source"]) - mean_x) ** 2
        for weight, item in zip(weights, anchors)
    )
    if denominator <= 1.0e-9:
        return None

    scale = sum(
        weight
        * (float(item["source"]) - mean_x)
        * (float(item["asr"]) - mean_y)
        for weight, item in zip(weights, anchors)
    ) / denominator
    offset = mean_y - scale * mean_x

    return scale, offset

def fit_timing_model(
    anchors: list[dict],
) -> dict:
    """Fit the simplest robust source->recording timing correction.

    Identity is preferred, then a constant offset, then an affine drift model.
    The affine model is accepted only when it materially improves residual
    consistency across a broad temporal span. This prevents sparse Whisper
    segment boundaries from becoming synthetic per-line timestamps.
    """
    if len(anchors) < 4:
        return {
            "kind": "insufficient",
            "scale": 1.0,
            "offset": 0.0,
            "inlier_lines": set(),
            "median_error": float("inf"),
            "p90_error": float("inf"),
            "span": 0.0,
            "coherent": False,
        }

    anchors = sorted(
        anchors,
        key=lambda item: float(item["source"]),
    )
    source_span = (
        float(anchors[-1]["source"])
        - float(anchors[0]["source"])
    )

    def errors(scale: float, offset: float) -> list[float]:
        return [
            float(item["asr"])
            - (scale * float(item["source"]) + offset)
            for item in anchors
        ]

    identity_errors = errors(1.0, 0.0)
    identity_median = statistics.median(
        abs(value)
        for value in identity_errors
    )

    offset = statistics.median(
        float(item["asr"]) - float(item["source"])
        for item in anchors
    )
    offset_errors = errors(1.0, offset)
    offset_median = statistics.median(
        abs(value)
        for value in offset_errors
    )

    model_kind = "identity"
    scale = 1.0
    chosen_offset = 0.0
    chosen_median = identity_median

    if (
        abs(offset) >= 0.35
        and offset_median + 0.30 < chosen_median
    ):
        model_kind = "offset"
        chosen_offset = offset
        chosen_median = offset_median

    slopes: list[float] = []
    if source_span >= 30.0:
        for left_index, left in enumerate(anchors):
            for right in anchors[left_index + 1:]:
                source_delta = (
                    float(right["source"])
                    - float(left["source"])
                )
                if source_delta < 12.0:
                    continue

                candidate = (
                    float(right["asr"])
                    - float(left["asr"])
                ) / source_delta

                if 0.92 <= candidate <= 1.08:
                    slopes.append(candidate)

    if slopes:
        affine_scale = statistics.median(slopes)
        affine_offset = statistics.median(
            float(item["asr"])
            - affine_scale * float(item["source"])
            for item in anchors
        )
        affine_errors = errors(
            affine_scale,
            affine_offset,
        )
        affine_median = statistics.median(
            abs(value)
            for value in affine_errors
        )

        # Accept gradual drift only when it has broad temporal evidence and
        # improves the robust median by a meaningful margin. A fixed 300 ms
        # hurdle was too coarse for otherwise-clean songs: it could leave a
        # real 1–2% clock drift uncorrected even when ten consistent anchors
        # made the affine model essentially exact. The bounded relative/floor
        # threshold remains deliberately conservative against noise-fitting.
        affine_improvement_required = max(
            0.12,
            min(0.30, chosen_median * 0.40),
        )
        if (
            source_span >= 30.0
            and abs(affine_scale - 1.0) >= 0.003
            and affine_median + affine_improvement_required < chosen_median
        ):
            model_kind = "affine"
            scale = affine_scale
            chosen_offset = affine_offset
            chosen_median = affine_median

    initial_errors = errors(scale, chosen_offset)
    center = statistics.median(initial_errors)
    mad = statistics.median(
        abs(value - center)
        for value in initial_errors
    )
    threshold = max(1.50, 2.50 * mad)

    inliers = [
        item
        for item, residual
        in zip(anchors, initial_errors)
        if abs(residual - center) <= threshold
    ]

    if model_kind == "affine" and len(inliers) >= 4:
        fitted = _weighted_linear_fit(inliers)
        if fitted is not None:
            fitted_scale, fitted_offset = fitted
            if 0.92 <= fitted_scale <= 1.08:
                scale = fitted_scale
                chosen_offset = fitted_offset

    elif model_kind == "offset" and inliers:
        chosen_offset = statistics.median(
            float(item["asr"]) - float(item["source"])
            for item in inliers
        )

    final_errors = [
        float(item["asr"])
        - (scale * float(item["source"]) + chosen_offset)
        for item in anchors
    ]
    final_center = statistics.median(final_errors)
    final_mad = statistics.median(
        abs(value - final_center)
        for value in final_errors
    )
    final_threshold = max(1.50, 2.50 * final_mad)

    final_inliers = [
        item
        for item, residual
        in zip(anchors, final_errors)
        if abs(residual - final_center) <= final_threshold
    ]

    inlier_errors = [
        abs(
            float(item["asr"])
            - (scale * float(item["source"]) + chosen_offset)
        )
        for item in final_inliers
    ]

    median_error = (
        statistics.median(inlier_errors)
        if inlier_errors
        else float("inf")
    )
    p90_error = (
        _percentile(inlier_errors, 0.90)
        if inlier_errors
        else float("inf")
    )

    required_inliers = max(
        4,
        math.ceil(len(anchors) * 0.60),
    )

    coherent = (
        len(final_inliers) >= required_inliers
        and source_span >= 20.0
        and median_error <= 2.25
        and p90_error <= 4.50
        and 0.92 <= scale <= 1.08
    )

    return {
        "kind": model_kind,
        "scale": scale,
        "offset": chosen_offset,
        "inlier_lines": {
            int(item["line_index"])
            for item in final_inliers
        },
        "median_error": median_error,
        "p90_error": p90_error,
        "span": source_span,
        "coherent": coherent,
    }

def _output_has_synthetic_fraction_pattern(
    rows: list[tuple[float, str]],
) -> bool:
    entries = [
        {"text": text, "source_time": start}
        for start, text in rows
    ]
    return timing_pattern_is_suspicious(entries)

def align_lyrics(
    entries: list[dict] | list[str],
    segments: list[dict],
) -> dict:
    """Verify lyric text and conservatively repair its timing.

    Selected LRC text remains authoritative unless the user edits the preview.
    ASR provides text evidence and a smooth source->recording timing model; it
    never silently replaces lyric words. Untimed lines may use a strong local
    ASR match, but equal-gap interpolation is never used.
    """
    if entries and isinstance(entries[0], str):
        entries = [
            {"text": str(text), "source_time": None}
            for text in entries
        ]

    entries = list(entries)
    n = len(entries)
    m = len(segments)

    if n == 0:
        raise VerseLatchError(
            "Lyrics file contains no usable text."
        )
    if m == 0:
        raise VerseLatchError(
            "No usable vocal evidence was found in the full recording."
        )

    mapped = _map_lyrics_to_segments(entries, segments)

    strong_threshold = 0.68
    support_threshold = 0.52

    strong_matches = {
        index
        for index, item in enumerate(mapped)
        if item is not None
        and float(item["score"]) >= strong_threshold
    }
    support_matches = {
        index
        for index, item in enumerate(mapped)
        if item is not None
        and float(item["score"]) >= support_threshold
    }

    timed_indices = [
        index
        for index, entry in enumerate(entries)
        if entry.get("source_time") is not None
    ]

    anchors = [
        {
            "line_index": index,
            "source": float(entries[index]["source_time"]),
            "asr": float(mapped[index]["start"]),
            "score": float(mapped[index]["score"]),
        }
        for index in sorted(support_matches)
        if entries[index].get("source_time") is not None
    ]

    model = fit_timing_model(anchors)
    inlier_lines = set(model["inlier_lines"])
    strong_inliers = strong_matches & inlier_lines
    support_inliers = support_matches & inlier_lines

    rows: list[tuple[float, str]] = []
    untimed_missing: set[int] = set()
    retimed_lines = 0

    for index, entry in enumerate(entries):
        source_time = entry.get("source_time")

        if source_time is not None:
            original = float(source_time)
            if model["coherent"]:
                corrected = (
                    float(model["scale"]) * original
                    + float(model["offset"])
                )
                if abs(corrected - original) >= 0.05:
                    retimed_lines += 1
            else:
                corrected = original

            rows.append((max(0.0, corrected), str(entry["text"])))
            continue

        mapped_item = mapped[index]
        if (
            mapped_item is not None
            and float(mapped_item["score"]) >= strong_threshold
        ):
            rows.append(
                (
                    max(0.0, float(mapped_item["start"])),
                    str(entry["text"]),
                )
            )
        else:
            untimed_missing.add(index)

    complete = len(rows) == n
    monotonic = all(
        right[0] > left[0]
        for left, right in zip(rows, rows[1:])
    )

    review_indices: set[int] = set(untimed_missing)
    suspicious: list[dict] = []

    for index, item in enumerate(mapped):
        if item is None:
            review_indices.add(index)
            suspicious.append(
                {
                    "expected": str(entries[index]["text"]),
                    "heard": "(no reliable local ASR window)",
                    "score": 0.0,
                    "reason": "no text evidence",
                }
            )
            continue

        score = float(item["score"])
        if score < strong_threshold:
            review_indices.add(index)
            suspicious.append(
                {
                    "expected": str(entries[index]["text"]),
                    "heard": str(item["evidence"]),
                    "score": score,
                    "reason": (
                        "supporting text evidence"
                        if score >= support_threshold
                        else "weak text evidence"
                    ),
                }
            )

    timing_outliers: set[int] = set()
    if model["kind"] != "insufficient":
        timing_outliers = {
            int(item["line_index"])
            for item in anchors
            if int(item["line_index"]) not in inlier_lines
        }

    for index in sorted(timing_outliers):
        review_indices.add(index)
        if index in {
            item_index
            for item_index, item in enumerate(mapped)
            if item is None or float(item["score"]) < strong_threshold
        }:
            continue
        suspicious.append(
            {
                "expected": str(entries[index]["text"]),
                "heard": str(mapped[index]["evidence"]),
                "score": float(mapped[index]["score"]),
                "reason": "timing outlier",
            }
        )

    inlier_count = len(support_inliers)
    inlier_coverage = inlier_count / n
    strong_coverage = len(strong_inliers) / n
    mean_score = (
        sum(float(mapped[index]["score"]) for index in support_inliers)
        / inlier_count
        if inlier_count
        else 0.0
    )

    timing_coherence = (
        max(0.0, min(1.0, 1.0 - float(model["median_error"]) / 3.0))
        if math.isfinite(float(model["median_error"]))
        else 0.0
    )

    timed_source_span = (
        float(entries[timed_indices[-1]]["source_time"])
        - float(entries[timed_indices[0]]["source_time"])
        if len(timed_indices) >= 2
        else 0.0
    )
    span_ratio = (
        min(1.0, float(model["span"]) / timed_source_span)
        if timed_source_span > 0.0
        else inlier_coverage
    )

    confidence = max(
        0.0,
        min(
            1.0,
            0.25 * inlier_coverage
            + 0.25 * strong_coverage
            + 0.20 * mean_score
            + 0.20 * timing_coherence
            + 0.10 * span_ratio,
        ),
    )

    source_timed_enough = (
        len(timed_indices) >= max(3, math.ceil(n * 0.80))
    )
    synthetic_output = complete and _output_has_synthetic_fraction_pattern(rows)

    safe = (
        complete
        and monotonic
        and not synthetic_output
        and model["coherent"]
        and source_timed_enough
        and len(support_inliers) >= max(4, math.ceil(n * 0.60))
        and len(strong_inliers) >= max(3, math.ceil(n * 0.40))
        and len(review_indices) <= max(2, math.ceil(n * 0.25))
        and confidence >= 0.68
    )

    return {
        "rows": rows,
        "confidence": confidence,
        "anchors": len(support_inliers),
        "direct_anchors": len(strong_matches),
        "strong_matches": len(strong_matches),
        "support_matches": len(support_matches),
        "model_anchors": len(support_inliers),
        "source_adjusted": retimed_lines,
        "retimed_lines": retimed_lines,
        "total": n,
        "suspicious": suspicious,
        "review_count": len(review_indices),
        "safe": safe,
        "timing_model": str(model["kind"]),
        "timing_scale": float(model["scale"]),
        "timing_offset": float(model["offset"]),
        "timing_median_error": float(model["median_error"]),
        "timing_p90_error": float(model["p90_error"]),
        "timing_coherent": bool(model["coherent"]),
        "complete": complete,
        "monotonic": monotonic,
        "synthetic_output": synthetic_output,
    }
