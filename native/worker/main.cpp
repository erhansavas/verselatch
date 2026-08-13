// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "asr.h"
#include "audio_decode.h"
#include "path_safety.h"
#include "worker_protocol.h"

#include <exception>
#include <string>
#include <vector>

namespace {
const char * asr_error_code(AsrFailure failure) {
    return failure == AsrFailure::invalid_model ? "INVALID_MODEL" : "ASR_FAILED";
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
        if (!verselatch_safe_regular_path(request.audio_ref)) {
            worker_write_error(
                request.request_id,
                "INVALID_REQUEST",
                "audio reference must name an existing absolute non-symlink regular file"
            );
            return 2;
        }
        if (!verselatch_safe_regular_path(request.model_ref)) {
            worker_write_error(
                request.request_id,
                "INVALID_MODEL",
                "verified model reference must name an existing absolute non-symlink regular file"
            );
            return 3;
        }

        std::vector<float> pcm;
        if (!verselatch_decode_audio(request.audio_ref, pcm, error)) {
            worker_write_error(request.request_id, "AUDIO_DECODE_FAILED", error);
            return 4;
        }

        std::vector<WorkerSegment> segments;
        const AsrFailure asr_failure = verselatch_run_asr(request, pcm, segments, error);
        if (asr_failure != AsrFailure::none) {
            worker_write_error(request.request_id, asr_error_code(asr_failure), error);
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
