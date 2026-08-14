# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from verselatch_app.analysis import AnalysisOutcome
from verselatch_app.files import SaveReceipt
from verselatch_app.model import ModelRequirement
from verselatch_platform.posix_runtime import PosixRuntime, create_posix_runtime


@dataclass(frozen=True)
class DesktopAnalysisPresentation:
    """Toolkit-facing rendering data derived from the authoritative portable outcome."""

    result: dict[str, object]
    report: str


class DesktopRuntimeAdapter:
    """Thin desktop adapter over one authoritative ``PosixRuntime`` instance.

    GTK remains responsible only for presentation and scheduling work off the UI
    thread. Source identity, model verification, native job ownership, cancellation,
    stale-result rejection, review state, and Save all remain owned by PosixRuntime.
    """

    def __init__(self, runtime: PosixRuntime) -> None:
        self.runtime = runtime

    @property
    def busy(self) -> bool:
        return self.runtime.state.active_run_id is not None

    @property
    def has_result(self) -> bool:
        return self.runtime.state.result is not None

    def set_sources(self, *, audio_path: Path | None, lyrics_path: Path | None) -> None:
        audio = (
            self.runtime.files.identify_audio(str(audio_path.resolve()))
            if audio_path is not None
            else None
        )
        lyrics = (
            self.runtime.files.identify_lyrics(str(lyrics_path.resolve()))
            if lyrics_path is not None
            else None
        )
        self.runtime.analysis.set_sources(audio=audio, lyrics=lyrics)

    def set_language(self, language: str) -> None:
        self.runtime.analysis.set_language(language)

    def start(
        self,
        *,
        audio_path: Path,
        lyrics_path: Path | None,
        language: str,
        model_requirement: ModelRequirement,
    ) -> int:
        self.set_sources(audio_path=audio_path, lyrics_path=lyrics_path)
        self.set_language(language)
        model = self.runtime.verify_model(model_requirement)
        if not model.ready:
            raise RuntimeError("configured ASR model failed exact verification")
        return self.runtime.analysis.start(model=model).run_id

    def finish(self, *, timeout: float | None = None) -> DesktopAnalysisPresentation | None:
        outcome = self.runtime.analysis.finish(timeout=timeout)
        if outcome is None:
            return None
        return present_analysis_outcome(outcome)

    def cancel(self) -> None:
        self.runtime.analysis.cancel()

    def edit_preview(self, text: str) -> None:
        self.runtime.state.edit_preview(text)

    def confirm_review(self, confirmed: bool) -> None:
        self.runtime.state.confirm_review(confirmed)

    def save(self) -> SaveReceipt:
        return self.runtime.save.save()

    def begin_close(self) -> None:
        self.runtime.analysis.begin_close()


def create_desktop_runtime_adapter(
    *,
    worker_path: str,
    model_path: str,
) -> DesktopRuntimeAdapter:
    return DesktopRuntimeAdapter(
        create_posix_runtime(worker_path=worker_path, model_path=model_path)
    )


def _report_lines(outcome: AnalysisOutcome) -> list[str]:
    lines = [
        f"MODE          {'VERIFY + RETIME' if outcome.kind == 'aligned' else 'GENERATE DRAFT'}",
        "ENGINE        package-owned verselatch-worker",
        "NETWORK       none",
        f"AUTO GATE     {'pass' if outcome.automatic_gate_passed else 'review required'}",
        "WRITE STATUS  explicit preview review required",
    ]
    rhythm = outcome.details.get("rhythm")
    if isinstance(rhythm, dict):
        beats = rhythm.get("beats", 0)
        onsets = rhythm.get("onsets", 0)
        beat_count = (
            beats
            if isinstance(beats, int) and not isinstance(beats, bool) and beats >= 0
            else 0
        )
        onset_count = (
            onsets
            if isinstance(onsets, int) and not isinstance(onsets, bool) and onsets >= 0
            else 0
        )
        lines.extend(
            [
                f"BEATS         {beat_count}",
                f"TRANSIENTS    {onset_count}",
            ]
        )
    return lines


def present_analysis_outcome(outcome: AnalysisOutcome) -> DesktopAnalysisPresentation:
    """Map portable domain evidence to the existing GTK structured-result vocabulary."""

    result: dict[str, object] = {
        "kind": outcome.kind,
        "allowed": outcome.automatic_gate_passed,
        "preview": outcome.result.preview,
    }

    if outcome.kind == "aligned":
        alignment = outcome.details.get("alignment")
        if isinstance(alignment, dict):
            # Preserve the existing GTK metric vocabulary without granting the
            # presentation layer any authority over domain decisions.
            for key in (
                "confidence",
                "anchors",
                "direct_anchors",
                "strong_matches",
                "support_matches",
                "model_anchors",
                "retimed_lines",
                "source_adjusted",
                "total",
                "review_count",
                "suspicious_count",
            ):
                if key in alignment:
                    result[key] = alignment[key]

    elif outcome.kind in {"generated", "generated-review", "generated-empty"}:
        draft_quality = outcome.details.get("draft_quality")
        if isinstance(draft_quality, dict):
            result["draft_quality"] = dict(draft_quality)
        result["dropped_non_lyrics"] = int(outcome.details.get("dropped_non_lyrics", 0) or 0)

    report = "\n".join(_report_lines(outcome)) + "\n"
    return DesktopAnalysisPresentation(result=result, report=report)
