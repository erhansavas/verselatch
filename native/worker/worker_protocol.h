// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <cstdint>
#include <string>
#include <vector>

struct WorkerRequest {
    std::uint64_t request_id = 0;
    std::string audio_ref;
    std::string model_ref;
    std::string language;
};

struct WorkerSegment {
    double start = 0.0;
    double end = 0.0;
    std::string text;
};

bool worker_read_request(WorkerRequest & request, std::string & error);
void worker_write_error(std::uint64_t request_id, const char * code, const std::string & message);
void worker_write_analysis(std::uint64_t request_id, const std::vector<WorkerSegment> & segments);
