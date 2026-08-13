# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.session import AnalysisResult, SourceIdentity, WorkflowState


def source(name: str, revision: int) -> SourceIdentity:
    return SourceIdentity(name, revision)


def result(
    audio: SourceIdentity,
    lyrics: SourceIdentity | None = None,
    *,
    preview: str = "[00:01.00]line\n",
    save_allowed_after_review: bool = True,
) -> AnalysisResult:
    return AnalysisResult(
        preview=preview,
        audio=audio,
        lyrics=lyrics,
        save_allowed_after_review=save_allowed_after_review,
    )


def test_analysis_requires_audio_and_only_one_active_run() -> None:
    state = WorkflowState()
    with pytest.raises(ValueError):
        state.begin_analysis()

    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)
    assert state.begin_analysis() == 1
    with pytest.raises(RuntimeError):
        state.begin_analysis()


def test_source_change_during_analysis_invalidates_and_requests_cancel() -> None:
    state = WorkflowState()
    audio_v1 = source("song.flac", 1)
    audio_v2 = source("song.flac", 2)
    state.set_sources(audio=audio_v1, lyrics=None)
    run_id = state.begin_analysis()

    state.set_sources(audio=audio_v2, lyrics=None)

    assert state.cancel_requested is True
    assert state.finish_analysis(run_id, result(audio_v1)) is False
    assert state.result is None
    assert state.save_eligible is False


def test_stale_completion_cannot_replace_newer_run() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)

    old_run = state.begin_analysis()
    assert state.finish_cancelled(old_run) is True
    new_run = state.begin_analysis()

    assert state.finish_analysis(old_run, result(audio)) is False
    assert state.active_run_id == new_run
    assert state.result is None

    assert state.finish_analysis(new_run, result(audio)) is True
    assert state.preview == "[00:01.00]line\n"


def test_cancel_request_wins_completion_race() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()

    state.request_cancel()

    assert state.finish_analysis(run_id, result(audio)) is False
    assert state.active_run_id is None
    assert state.result is None
    assert state.save_eligible is False


def test_review_is_explicit_and_editing_revokes_confirmation() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, result(audio)) is True

    assert state.save_eligible is False
    state.confirm_review(True)
    assert state.save_eligible is True

    state.edit_preview("[00:01.00]corrected line\n")
    assert state.review_confirmed is False
    assert state.save_eligible is False


def test_automatic_gate_can_forbid_save_even_after_review() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    blocked = result(audio, save_allowed_after_review=False)
    assert state.finish_analysis(run_id, blocked) is True

    state.confirm_review(True)
    assert state.save_eligible is False


def test_revalidation_rejects_replaced_lyrics_after_analysis() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    lyrics_v1 = source("lyrics.txt", 1)
    lyrics_v2 = source("lyrics.txt", 2)
    state.set_sources(audio=audio, lyrics=lyrics_v1)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, result(audio, lyrics_v1)) is True
    state.confirm_review(True)
    assert state.save_eligible is True

    assert state.revalidate_sources(audio=audio, lyrics=lyrics_v2) is False
    assert state.result is None
    assert state.save_eligible is False


def test_language_change_invalidates_result() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, result(audio)) is True
    state.confirm_review(True)

    state.set_language("TR")

    assert state.language == "tr"
    assert state.result is None
    assert state.save_eligible is False


def test_empty_preview_cannot_be_confirmed() -> None:
    state = WorkflowState()
    audio = source("song.flac", 1)
    state.set_sources(audio=audio, lyrics=None)
    run_id = state.begin_analysis()
    assert state.finish_analysis(run_id, result(audio, preview="")) is True

    with pytest.raises(ValueError):
        state.confirm_review(True)
