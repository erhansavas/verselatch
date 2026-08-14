# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from verselatch_app.analysis import build_analysis_outcome
from verselatch_app.backend import AnalysisEvidence
from verselatch_app.session import SourceIdentity
from verselatch_core import VerseLatchError


def source(name: str) -> SourceIdentity:
    return SourceIdentity(name, ("revision", 1))


def test_verify_align_requires_lyrics_text() -> None:
    with pytest.raises(ValueError, match="lyrics text"):
        build_analysis_outcome(
            audio=source("content://audio/4"),
            lyrics=source("content://lyrics/4"),
            lyrics_text=None,
            evidence=AnalysisEvidence(segments=()),
        )


def test_verify_align_rejects_empty_lyrics() -> None:
    with pytest.raises(VerseLatchError, match="no usable text"):
        build_analysis_outcome(
            audio=source("content://audio/5"),
            lyrics=source("content://lyrics/5"),
            lyrics_text="\n\n",
            evidence=AnalysisEvidence(segments=()),
        )
