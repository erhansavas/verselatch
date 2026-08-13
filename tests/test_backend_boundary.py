# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.backend import AnalysisBackend, AnalysisJob, AnalysisRequest
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import AnalysisResult, SourceIdentity


class FakeJob:
    def __init__(self, result: AnalysisResult) -> None:
        self._result = result
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def result(self, timeout: float | None = None) -> AnalysisResult:
        return self._result


class FakeBackend:
    def __init__(self, job: FakeJob) -> None:
        self.job = job
        self.requests: list[AnalysisRequest] = []

    def start(self, request: AnalysisRequest) -> FakeJob:
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


def test_analysis_backend_boundary_has_no_process_api() -> None:
    audio = SourceIdentity("content://media/audio/42", ("etag", 7))
    expected = AnalysisResult(
        preview="[00:01.00]line\n",
        audio=audio,
        lyrics=None,
        save_allowed_after_review=True,
    )
    job = FakeJob(expected)
    backend = FakeBackend(job)
    request = AnalysisRequest(
        audio=audio,
        lyrics=None,
        language="tr",
        model=verified_model(),
    )

    assert isinstance(job, AnalysisJob)
    assert isinstance(backend, AnalysisBackend)
    started = backend.start(request)
    assert started.result() == expected
    started.cancel()
    assert job.cancelled is True
    assert backend.requests == [request]


def test_analysis_request_rejects_unverified_model() -> None:
    model = verified_model()
    bad = ModelVerification(
        requirement=model.requirement,
        source=model.source,
        actual_name=model.actual_name,
        actual_size=model.actual_size - 1,
        actual_sha256=model.actual_sha256,
    )

    with pytest.raises(ValueError, match="verification"):
        AnalysisRequest(audio=SourceIdentity("audio", 1), lyrics=None, language="auto", model=bad)
