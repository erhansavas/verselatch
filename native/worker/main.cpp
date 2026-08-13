// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "asr.h"
#include "audio_decode.h"
#include "worker_protocol.h"

#include <exception>
#include <filesystem>
#include <string>
#include <vector>

namespace {
bool regular_absolute_file(const std::string & value) {
    std::error_code error;
    const std::filesystem::path path(value);
    return path.is_absolute()
        && std::filesystem::is_regular_file(path, error)
        && !error;
}
}

int main() {
    WorkerRequest request;
    std::string error;
    if (!worker_read_request(request, error)) {
        worker_write_error(request.request_id, "INVALID_REQUEST", error);
        return 2;
    }

    try {
        if (!regular_absolute_file(request.audio_ref)) {
            worker_write_error(
                request.request_id,
                "INVALID_REQUEST",
                "audio reference must name an existing absolute regular file"
            );
            return 2;
        }
        if (!regular_absolute_file(request.model_ref)) {
            worker_write_error(
                request.request_id,
                "INVALID_MODEL",
                "verified model reference is not an existing absolute regular file"
            );
            return 3;
        }

        std::vector<float> pcm;
        if (!verselatch_decode_audio(request.audio_ref, pcm, error)) {
            worker_write_error(request.request_id, "AUDIO_DECODE_FAILED", error);
            return 4;
        }

        std::vector<WorkerSegment> segments;
        if (!verselatch_run_asr(request, pcm, segments, error)) {
            const char * code = error.find("model") != std::string::npos
                ? "INVALID_MODEL"
                : "ASR_FAILED";
            worker_write_error(request.request_id, code, error);
            return 5;
        }

        worker_write_analysis(request.request_id, segments);
        return 0;
    } catch (const std::exception &) {
        worker_write_error(request.request_id, "INTERNAL_ERROR", "native worker failed safely");
        return 6;
    } catch (...) {
        worker_write_error(request.request_id, "INTERNAL_ERROR", "native worker failed safely");
        return 6;
    }
}
