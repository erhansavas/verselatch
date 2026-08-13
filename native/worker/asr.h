// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include "worker_protocol.h"

#include <string>
#include <vector>

enum class AsrFailure {
    none,
    invalid_model,
    inference_failed,
    invalid_evidence,
};

AsrFailure verselatch_run_asr(
    const WorkerRequest & request,
    const std::vector<float> & pcm,
    std::vector<WorkerSegment> & segments,
    std::string & error
);
