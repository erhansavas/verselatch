# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

class VerseLatchError(RuntimeError):
    """Expected user-facing VerseLatch validation or workflow error."""


class AnalysisCancelled(VerseLatchError):
    """Internal control-flow signal for a user-requested analysis cancellation."""

    def __init__(self) -> None:
        super().__init__("Analysis cancelled.")
