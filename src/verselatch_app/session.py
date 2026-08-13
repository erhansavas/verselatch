# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceIdentity:
    """Stable identity for a selected source at one point in time.

    ``location`` is deliberately an opaque string: desktop paths and Android
    document URIs can both be represented without teaching workflow state
    about a platform filesystem. ``revision`` is supplied by the platform
    adapter and changes whenever the source must be treated as stale.
    """

    location: str
    revision: object


@dataclass(frozen=True)
class AnalysisResult:
    preview: str
    audio: SourceIdentity
    lyrics: SourceIdentity | None
    save_allowed_after_review: bool


class WorkflowState:
    """Toolkit-neutral correctness state for one VerseLatch workflow session."""

    def __init__(self) -> None:
        self.audio: SourceIdentity | None = None
        self.lyrics: SourceIdentity | None = None
        self.language = "auto"

        self._next_run_id = 1
        self.active_run_id: int | None = None
        self.result: AnalysisResult | None = None
        self.review_confirmed = False
        self.preview = ""
        self.cancel_requested = False
        self.closing = False

    def set_sources(
        self,
        *,
        audio: SourceIdentity | None,
        lyrics: SourceIdentity | None,
    ) -> None:
        if audio == self.audio and lyrics == self.lyrics:
            return
        self.audio = audio
        self.lyrics = lyrics
        self._invalidate_result()
        self.cancel_requested = self.active_run_id is not None

    def set_language(self, language: str) -> None:
        normalized = language.strip().casefold() or "auto"
        if normalized == self.language:
            return
        self.language = normalized
        self._invalidate_result()
        self.cancel_requested = self.active_run_id is not None

    def begin_analysis(self) -> int:
        if self.closing:
            raise RuntimeError("workflow is closing")
        if self.audio is None:
            raise ValueError("audio source is required")
        if self.active_run_id is not None:
            raise RuntimeError("analysis is already active")

        run_id = self._next_run_id
        self._next_run_id += 1
        self.active_run_id = run_id
        self.cancel_requested = False
        self._invalidate_result()
        return run_id

    def request_cancel(self) -> None:
        if self.active_run_id is not None:
            self.cancel_requested = True

    def begin_close(self) -> None:
        """Invalidate user-visible state and cancel any owned active analysis."""
        if self.closing:
            return
        self.closing = True
        self._invalidate_result()
        self.cancel_requested = self.active_run_id is not None

    def finish_cancelled(self, run_id: int) -> bool:
        if run_id != self.active_run_id:
            return False
        self.active_run_id = None
        self.cancel_requested = False
        self._invalidate_result()
        return True

    def finish_failed(self, run_id: int) -> bool:
        if run_id != self.active_run_id:
            return False
        self.active_run_id = None
        self.cancel_requested = False
        self._invalidate_result()
        return True

    def finish_analysis(self, run_id: int, result: AnalysisResult) -> bool:
        """Accept a completion only when it still belongs to current inputs."""
        if run_id != self.active_run_id:
            return False

        cancelled = self.cancel_requested or self.closing
        self.active_run_id = None
        self.cancel_requested = False

        if cancelled:
            self._invalidate_result()
            return False

        if result.audio != self.audio or result.lyrics != self.lyrics:
            self._invalidate_result()
            return False

        self.result = result
        self.preview = result.preview
        self.review_confirmed = False
        return True

    def edit_preview(self, text: str) -> None:
        if self.result is None:
            raise RuntimeError("no analysis result is available")
        if text != self.preview:
            self.preview = text
            self.review_confirmed = False

    def confirm_review(self, confirmed: bool) -> None:
        if confirmed and not self.preview.strip():
            raise ValueError("an empty preview cannot be approved")
        self.review_confirmed = bool(confirmed)

    def revalidate_sources(
        self,
        *,
        audio: SourceIdentity | None,
        lyrics: SourceIdentity | None,
    ) -> bool:
        """Fail closed when a selected source changed after analysis."""
        if audio != self.audio or lyrics != self.lyrics:
            self.set_sources(audio=audio, lyrics=lyrics)
            return False
        if self.result is None:
            return False
        if self.result.audio != audio or self.result.lyrics != lyrics:
            self._invalidate_result()
            return False
        return True

    @property
    def analysis_state(self) -> str:
        if self.closing:
            return "closing"
        if self.active_run_id is not None:
            return "cancelling" if self.cancel_requested else "running"
        if self.result is not None:
            return "completed"
        return "idle"

    @property
    def save_eligible(self) -> bool:
        return (
            not self.closing
            and self.result is not None
            and self.result.save_allowed_after_review
            and bool(self.preview.strip())
            and self.review_confirmed
            and self.active_run_id is None
            and self.result.audio == self.audio
            and self.result.lyrics == self.lyrics
        )

    def _invalidate_result(self) -> None:
        self.result = None
        self.preview = ""
        self.review_confirmed = False
