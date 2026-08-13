# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from .files import FileService, SaveReceipt, SaveRequest
from .session import WorkflowState


class SaveController:
    """Perform one explicit reviewed Save through the semantic file boundary."""

    def __init__(self, *, state: WorkflowState, files: FileService) -> None:
        self.state = state
        self.files = files

    def save(self) -> SaveReceipt:
        result = self.state.result
        if result is None or not self.state.save_eligible:
            raise RuntimeError("reviewed result is not eligible for saving")

        # FileService owns source revalidation and the safe write as one
        # platform-native operation. A separate pre-check here would create a
        # check/use race instead of improving safety.
        request = SaveRequest(
            content=self.state.preview,
            audio=result.audio,
            lyrics=result.lyrics,
        )
        return self.files.save_reviewed_lrc(request)
