# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from verselatch_app.session import WorkflowState


def test_workflow_starts_open() -> None:
    state = WorkflowState()
    assert state.closing is False
