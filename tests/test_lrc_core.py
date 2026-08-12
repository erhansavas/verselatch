# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import math
import random

import pytest

from verselatch_core import (
    VerseLatchError,
    normalize,
    parse_lyric_document,
    parse_reviewed_lrc,
    render_lrc,
    same_lyric_text,
    timing_pattern_is_suspicious,
)


def test_normalize_is_unicode_stable_and_idempotent():
    samples = [
        "We're HERE!",
        "İstanbul’da gece",
        "  déjà-vu — déjà vu  ",
        "ÇAĞRI / çağrı",
        "rock’n’roll",
    ]
    for sample in samples:
        once = normalize(sample)
        assert normalize(once) == once
        assert "  " not in once


def test_parse_handles_bom_crlf_metadata_and_multi_timestamp_lines():
    source = (
        "\ufeff[ar:Fictional Artist]\r\n"
        "[00:01.20][00:05.40]gökyüzü açık\r\n"
        "plain lyric\r\n"
        "[00:09.00]\r\n"
    )
    entries = parse_lyric_document(source)["entries"]
    assert entries == [
        {"text": "gökyüzü açık", "source_time": 1.2},
        {"text": "gökyüzü açık", "source_time": 5.4},
        {"text": "plain lyric", "source_time": None},
    ]


def test_reviewed_lrc_requires_strict_monotonic_finite_rows():
    assert parse_reviewed_lrc(
        "[00:01.00]ilk satır\n[00:02.25]ikinci satır\n"
    ) == [(1.0, "ilk satır"), (2.25, "ikinci satır")]

    for invalid in (
        "[00:02.00]later\n[00:01.00]earlier\n",
        "[00:01.00]first\n[00:01.00]duplicate\n",
        "no timestamp\n",
        "[00:99.00]bad seconds\n",
    ):
        with pytest.raises(VerseLatchError):
            parse_reviewed_lrc(invalid)


def test_render_parse_roundtrip_preserves_text_and_quantized_time():
    rng = random.Random(0x564C)
    rows = []
    current = 0.0
    for index in range(80):
        current += rng.uniform(0.05, 8.0)
        rows.append((current, f"satır {index} çığ öşü"))

    rendered = render_lrc(rows)
    parsed = parse_reviewed_lrc(rendered)
    assert [text for _, text in parsed] == [text for _, text in rows]
    for (original, _), (roundtripped, _) in zip(rows, parsed):
        assert math.isclose(roundtripped, round(original * 100) / 100, abs_tol=0.011)


def test_synthetic_fraction_detector_is_conservative():
    synthetic = parse_lyric_document(
        "\n".join(
            f"[00:{1 + index * 3:02d}.88]line {index}"
            for index in range(10)
        )
    )["entries"]
    assert timing_pattern_is_suspicious(synthetic)

    natural = parse_lyric_document(
        "\n".join(
            f"[00:{1 + index * 3:02d}.{(11 + index * 7) % 100:02d}]line {index}"
            for index in range(10)
        )
    )["entries"]
    assert not timing_pattern_is_suspicious(natural)


def test_matching_normalization_handles_turkish_i_diacritics_and_apostrophes():
    assert normalize("İSTANBUL") == normalize("istanbul") == "istanbul"
    assert normalize("IŞIK") == normalize("ışık") == "isik"
    assert normalize("café") == normalize("cafe") == "cafe"
    assert normalize("Ankara'nın") == normalize("Ankaranin") == "ankaranin"


def test_same_lyric_text_is_matching_only_and_never_mutates_authoritative_text():
    left = [{"text": "İstanbul’da Gece", "source_time": 1.2}]
    right = [{"text": "istanbulda gece", "source_time": 99.9}]
    original = [dict(item) for item in left]
    assert same_lyric_text(left, right)
    assert left == original
    assert not same_lyric_text(left, [{"text": "başka satır", "source_time": 1.2}])
