# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass

from .analysis import AnalysisOutcome, build_analysis_outcome
from .backend import EvidenceBackend, EvidenceJob, EvidenceRequest
from .files import FileService
from .model import ModelVerification
from .session import SourceIdentity, WorkflowState


@dataclass(frozen=True)
class ActiveAnalysis:
    run_id: int
    job: EvidenceJob
    audio: SourceIdentity
    lyrics: SourceIdentity | None
    lyrics_text: str | None


class AnalysisController:
    """Coordinate workflow, semantic file services, and native evidence jobs."""

    def __init__(
        self,
        *,
        state: WorkflowState,
        files: FileService,
        backend: EvidenceBackend,
    ) -> None:
        self.state = state
        self.files = files
        self.backend = backend
        self._active: ActiveAnalysis | None = None

    @property
    def active(self) -> ActiveAnalysis | None:
        return self._active

    def set_sources(
        self,
        *,
        audio: SourceIdentity | None,
        lyrics: SourceIdentity | None,
    ) -> None:
        self.state.set_sources(audio=audio, lyrics=lyrics)
        if self.state.cancel_requested:
            self.cancel()

    def set_language(self, language: str) -> None:
        self.state.set_language(language)
        if self.state.cancel_requested:
            self.cancel()

    def start(self, *, model: ModelVerification) -> ActiveAnalysis:
        run_id = self.state.begin_analysis()
        audio = self.state.audio
        lyrics = self.state.lyrics
        assert audio is not None

        try:
            if not self.files.revalidate(audio):
                raise RuntimeError("audio source changed before analysis")

            lyrics_text: str | None = None
            if lyrics is not None:
                document = self.files.read_lyrics(lyrics)
                if document.source != lyrics:
                    raise RuntimeError("lyrics source changed while being read")
                lyrics_text = document.text

            request = EvidenceRequest(
                audio=audio,
                language=self.state.language,
                model=model,
            )
            job = self.backend.start(request)
        except Exception:
            self.state.finish_failed(run_id)
            raise

        active = ActiveAnalysis(
            run_id=run_id,
            job=job,
            audio=audio,
            lyrics=lyrics,
            lyrics_text=lyrics_text,
        )
        self._active = active
        return active

    def cancel(self) -> None:
        self.state.request_cancel()
        active = self._active
        if active is not None:
            active.job.cancel()

    def finish(self, *, timeout: float | None = None) -> AnalysisOutcome | None:
        active = self._active
        if active is None:
            raise RuntimeError("no analysis is active")

        try:
            evidence = active.job.result(timeout)
            if self.state.cancel_requested:
                self.state.finish_cancelled(active.run_id)
                return None
            if not self.files.revalidate(active.audio):
                self.state.finish_failed(active.run_id)
                return None
            if active.lyrics is not None and not self.files.revalidate(active.lyrics):
                self.state.finish_failed(active.run_id)
                return None

            outcome = build_analysis_outcome(
                audio=active.audio,
                lyrics=active.lyrics,
                lyrics_text=active.lyrics_text,
                evidence=evidence,
            )
            if not self.state.finish_analysis(active.run_id, outcome.result):
                return None
            return outcome
        except Exception:
            if self.state.cancel_requested:
                self.state.finish_cancelled(active.run_id)
                return None
            self.state.finish_failed(active.run_id)
            raise
        finally:
            if self._active is active:
                self._active = None

    def begin_close(self) -> None:
        self.state.begin_close()
        active = self._active
        if active is not None:
            active.job.cancel()
