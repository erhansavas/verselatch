# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.backend import AnalysisBackend, AnalysisJob, AnalysisRequest
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
    request = AnalysisRequest(audio=audio, lyrics=None, language="tr")

    assert isinstance(job, AnalysisJob)
    assert isinstance(backend, AnalysisBackend)
    started = backend.start(request)
    assert started.result() == expected
    started.cancel()
    assert job.cancelled is True
    assert backend.requests == [request]
