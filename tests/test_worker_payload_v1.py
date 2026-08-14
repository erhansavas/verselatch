# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.worker_payload_v1 import (
    WorkerPayloadError,
    validate_worker_analysis_payload,
)


def valid_payload() -> dict[str, object]:
    return {
        "segments": [
            {
                "start": 0.5,
                "end": 1.2,
                "text": "silver morning",
                "token_confidence": 0.91,
                "low_confidence_fraction": 0.0,
                "token_count": 2,
                "words": [
                    {"text": "silver", "start": 0.5, "end": 0.8},
                    {"text": "morning", "start": 0.82, "end": 1.2},
                ],
            }
        ],
        "rhythm": {"beats": [0.4, 0.9], "onsets": [0.5, 1.0]},
    }


def test_payload_is_canonicalized_through_domain_validator() -> None:
    payload = validate_worker_analysis_payload(valid_payload())
    assert payload["segments"][0]["text"] == "silver morning"
    assert payload["rhythm"] == {"beats": [0.4, 0.9], "onsets": [0.5, 1.0]}


def test_empty_evidence_is_valid_success() -> None:
    assert validate_worker_analysis_payload({"segments": [], "rhythm": {}}) == {
        "segments": [],
        "rhythm": {},
    }


def test_unknown_payload_or_segment_fields_are_rejected() -> None:
    with pytest.raises(WorkerPayloadError, match="payload schema"):
        validate_worker_analysis_payload({"segments": [], "rhythm": {}, "extra": 1})

    payload = valid_payload()
    payload["segments"][0]["argv"] = ["unexpected"]
    with pytest.raises(WorkerPayloadError, match="segment schema"):
        validate_worker_analysis_payload(payload)


def test_segment_domain_invariants_are_reused() -> None:
    payload = valid_payload()
    payload["segments"][0]["end"] = 0.1
    with pytest.raises(WorkerPayloadError, match="domain validation"):
        validate_worker_analysis_payload(payload)


def test_word_schema_is_exact() -> None:
    payload = valid_payload()
    payload["segments"][0]["words"][0]["confidence"] = 1.0
    with pytest.raises(WorkerPayloadError, match="word schema"):
        validate_worker_analysis_payload(payload)


def test_rhythm_evidence_must_be_complete_and_monotonic() -> None:
    payload = valid_payload()
    payload["rhythm"] = {"beats": [0.5]}
    with pytest.raises(WorkerPayloadError, match="rhythm schema"):
        validate_worker_analysis_payload(payload)

    payload = valid_payload()
    payload["rhythm"]["beats"] = [0.5, 0.5]
    with pytest.raises(WorkerPayloadError, match="strictly increasing"):
        validate_worker_analysis_payload(payload)


def test_rhythm_rejects_nonfinite_numbers() -> None:
    payload = valid_payload()
    payload["rhythm"]["onsets"] = [0.5, float("inf")]
    with pytest.raises(WorkerPayloadError, match="finite"):
        validate_worker_analysis_payload(payload)
