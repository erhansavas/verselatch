# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from verselatch_app.analysis import AnalysisOutcome
from verselatch_app.files import SaveReceipt
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import AnalysisResult, SourceIdentity, WorkflowState
from verselatch_platform.gtk_runtime import (
    DesktopRuntimeAdapter,
    present_analysis_outcome,
)


class FakeFiles:
    def identify_audio(self, location: str) -> SourceIdentity:
        return SourceIdentity(location=location, revision=("audio", location))

    def identify_lyrics(self, location: str) -> SourceIdentity:
        return SourceIdentity(location=location, revision=("lyrics", location))


class FakeAnalysis:
    def __init__(self, state: WorkflowState) -> None:
        self.state = state
        self.started_model = None
        self.cancelled = False
        self.closed = False

    def set_sources(self, *, audio, lyrics) -> None:
        self.state.set_sources(audio=audio, lyrics=lyrics)

    def set_language(self, language: str) -> None:
        self.state.set_language(language)

    def start(self, *, model):
        self.started_model = model
        run_id = self.state.begin_analysis()

        @dataclass(frozen=True)
        class Active:
            run_id: int

        return Active(run_id)

    def finish(self, *, timeout=None):
        del timeout
        assert self.state.active_run_id is not None
        audio = self.state.audio
        assert audio is not None
        result = AnalysisResult(
            preview="[00:01.00]silver morning\n",
            audio=audio,
            lyrics=self.state.lyrics,
            save_allowed_after_review=True,
        )
        run_id = self.state.active_run_id
        assert self.state.finish_analysis(run_id, result)
        return AnalysisOutcome(
            result=result,
            kind="aligned",
            automatic_gate_passed=True,
            details={
                "alignment": {
                    "confidence": 0.97,
                    "strong_matches": 4,
                    "support_matches": 1,
                    "retimed_lines": 3,
                    "total": 4,
                    "review_count": 0,
                },
                "rhythm": {},
            },
        )

    def cancel(self) -> None:
        self.cancelled = True
        self.state.request_cancel()

    def begin_close(self) -> None:
        self.closed = True
        self.state.begin_close()


class FakeModels:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    def verify(self, requirement):
        return ModelVerification(
            requirement=requirement,
            source=SourceIdentity("/model", ("model", 1)),
            actual_name=requirement.name if self.ready else "wrong.bin",
            actual_size=requirement.size,
            actual_sha256=requirement.sha256,
        )


class FakeSave:
    def __init__(self, state: WorkflowState) -> None:
        self.state = state
        self.calls = 0

    def save(self):
        self.calls += 1
        if not self.state.save_eligible:
            raise RuntimeError("not eligible")
        return SaveReceipt(
            output=SourceIdentity("/tmp/song.lrc", ("lyrics", 2)),
            backup=None,
        )


class FakeRuntime:
    def __init__(self, *, model_ready: bool = True) -> None:
        self.state = WorkflowState()
        self.files = FakeFiles()
        self.models = FakeModels(model_ready)
        self.analysis = FakeAnalysis(self.state)
        self.save = FakeSave(self.state)

    def verify_model(self, requirement):
        return self.models.verify(requirement)


REQ = ModelRequirement(name="ggml-large-v3-turbo.bin", size=10, sha256="a" * 64)


def test_desktop_adapter_start_uses_one_workflow_state(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    adapter = DesktopRuntimeAdapter(runtime)  # type: ignore[arg-type]
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fixture")

    run_id = adapter.start(
        audio_path=audio,
        lyrics_path=None,
        language=" TR ",
        model_requirement=REQ,
    )
    assert run_id == 1
    assert adapter.busy
    assert runtime.state.language == "tr"
    assert runtime.state.audio is not None
    assert runtime.analysis.started_model is not None


def test_desktop_adapter_rejects_unverified_model_before_analysis(tmp_path: Path) -> None:
    runtime = FakeRuntime(model_ready=False)
    adapter = DesktopRuntimeAdapter(runtime)  # type: ignore[arg-type]
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fixture")

    try:
        adapter.start(
            audio_path=audio,
            lyrics_path=None,
            language="auto",
            model_requirement=REQ,
        )
    except RuntimeError as exc:
        assert "exact verification" in str(exc)
    else:
        raise AssertionError("unverified model was accepted")
    assert not adapter.busy


def test_desktop_adapter_finish_preview_review_and_save(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    adapter = DesktopRuntimeAdapter(runtime)  # type: ignore[arg-type]
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fixture")
    adapter.start(
        audio_path=audio,
        lyrics_path=None,
        language="auto",
        model_requirement=REQ,
    )

    presentation = adapter.finish()
    assert presentation is not None
    assert not adapter.busy
    assert presentation.result["kind"] == "aligned"
    assert presentation.result["confidence"] == 0.97
    assert "package-owned verselatch-worker" in presentation.report

    adapter.edit_preview("[00:02.00]paper horizon\n")
    assert not runtime.state.review_confirmed
    adapter.confirm_review(True)
    assert runtime.state.save_eligible

    receipt = adapter.save()
    assert receipt.output.location == "/tmp/song.lrc"
    assert runtime.save.calls == 1


def test_desktop_adapter_cancel_and_close_delegate_to_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    adapter = DesktopRuntimeAdapter(runtime)  # type: ignore[arg-type]
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fixture")
    adapter.start(
        audio_path=audio,
        lyrics_path=None,
        language="auto",
        model_requirement=REQ,
    )
    adapter.cancel()
    assert runtime.analysis.cancelled
    assert runtime.state.cancel_requested

    adapter.begin_close()
    assert runtime.analysis.closed
    assert runtime.state.closing


def test_presentation_reports_native_rhythm_counts_as_counts() -> None:
    audio = SourceIdentity("/audio", ("audio", 1))
    result = AnalysisResult(
        preview="[00:01.00]silver morning\n",
        audio=audio,
        lyrics=None,
        save_allowed_after_review=True,
    )
    outcome = AnalysisOutcome(
        result=result,
        kind="generated",
        automatic_gate_passed=True,
        details={
            "draft_quality": {"safe": True},
            "dropped_non_lyrics": 0,
            "rhythm": {"beats": 17, "onsets": 29},
        },
    )
    presentation = present_analysis_outcome(outcome)
    assert "BEATS         17" in presentation.report
    assert "TRANSIENTS    29" in presentation.report


def test_generated_presentation_never_grants_write_authority() -> None:
    audio = SourceIdentity("/audio", ("audio", 1))
    result = AnalysisResult(
        preview="[00:01.00]silver morning\n",
        audio=audio,
        lyrics=None,
        save_allowed_after_review=True,
    )
    outcome = AnalysisOutcome(
        result=result,
        kind="generated-review",
        automatic_gate_passed=False,
        details={"draft_quality": {"safe": False}, "dropped_non_lyrics": 2, "rhythm": {}},
    )
    presentation = present_analysis_outcome(outcome)
    assert presentation.result["allowed"] is False
    assert presentation.result["dropped_non_lyrics"] == 2
    assert "explicit preview review required" in presentation.report
