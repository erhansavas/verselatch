# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.backend import (
    AnalysisEvidence,
    EvidenceBackend,
    EvidenceJob,
    EvidenceRequest,
)
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import SourceIdentity


class FakeJob:
    def __init__(self, result: AnalysisEvidence) -> None:
        self._result = result
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def result(self, timeout: float | None = None) -> AnalysisEvidence:
        return self._result


class FakeBackend:
    def __init__(self, job: FakeJob) -> None:
        self.job = job
        self.requests: list[EvidenceRequest] = []

    def start(self, request: EvidenceRequest) -> FakeJob:
        self.requests.append(request)
        return self.job


def verified_model() -> ModelVerification:
    requirement = ModelRequirement("model.bin", 4, "abcd")
    return ModelVerification(
        requirement=requirement,
        source=SourceIdentity("app-private://model", 1),
        actual_name="model.bin",
        actual_size=4,
        actual_sha256="ABCD",
    )


def test_evidence_backend_boundary_has_no_process_or_lyrics_api() -> None:
    audio = SourceIdentity("content://media/audio/42", ("etag", 7))
    expected = AnalysisEvidence(
        segments=({"start": 0.5, "end": 1.0, "text": "line"},),
        beats=(0.4, 0.9),
        onsets=(0.5,),
    )
    job = FakeJob(expected)
    backend = FakeBackend(job)
    request = EvidenceRequest(
        audio=audio,
        language="tr",
        model=verified_model(),
    )

    assert isinstance(job, EvidenceJob)
    assert isinstance(backend, EvidenceBackend)
    started = backend.start(request)
    assert started.result() == expected
    started.cancel()
    assert job.cancelled is True
    assert backend.requests == [request]
    assert not hasattr(request, "lyrics")


def test_evidence_request_rejects_unverified_model() -> None:
    model = verified_model()
    bad = ModelVerification(
        requirement=model.requirement,
        source=model.source,
        actual_name=model.actual_name,
        actual_size=model.actual_size - 1,
        actual_sha256=model.actual_sha256,
    )

    with pytest.raises(ValueError, match="verification"):
        EvidenceRequest(audio=SourceIdentity("audio", 1), language="auto", model=bad)


def test_evidence_request_requires_language() -> None:
    with pytest.raises(ValueError, match="language"):
        EvidenceRequest(
            audio=SourceIdentity("audio", 1),
            language=" ",
            model=verified_model(),
        )
