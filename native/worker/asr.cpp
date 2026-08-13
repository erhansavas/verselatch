// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "asr.h"

#include "model_loader.h"
#include "whisper.h"

#include <cstddef>
#include <limits>

bool verselatch_run_asr(
    const WorkerRequest & request,
    const std::vector<float> & pcm,
    std::vector<WorkerSegment> & segments,
    std::string & error
) {
    segments.clear();
    error.clear();
    if (pcm.empty() || pcm.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        error = "decoded PCM input is invalid";
        return false;
    }

    whisper_context_params context_params = whisper_context_default_params();
    context_params.use_gpu = false;
    whisper_context * context = verselatch_load_verified_model(
        request.model_ref,
        context_params,
        error
    );
    if (context == nullptr) {
        return false;
    }

    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.translate = false;
    params.no_context = true;
    params.print_special = false;
    params.print_progress = false;
    params.print_realtime = false;
    params.print_timestamps = false;
    params.language = request.language == "auto" ? "auto" : request.language.c_str();
    params.detect_language = request.language == "auto";

    const int status = whisper_full(
        context,
        params,
        pcm.data(),
        static_cast<int>(pcm.size())
    );
    if (status != 0) {
        whisper_free(context);
        error = "whisper inference failed";
        return false;
    }

    const int count = whisper_full_n_segments(context);
    if (count < 0 || count > 600) {
        whisper_free(context);
        error = "whisper produced an invalid segment count";
        return false;
    }

    double previous_start = -1.0;
    for (int index = 0; index < count; ++index) {
        const int64_t t0 = whisper_full_get_segment_t0(context, index);
        const int64_t t1 = whisper_full_get_segment_t1(context, index);
        const char * raw_text = whisper_full_get_segment_text(context, index);
        if (t0 < 0 || t1 < t0 || raw_text == nullptr) {
            whisper_free(context);
            error = "whisper produced invalid segment evidence";
            segments.clear();
            return false;
        }
        const double start = static_cast<double>(t0) / 100.0;
        const double end = static_cast<double>(t1) / 100.0;
        if (start < previous_start) {
            whisper_free(context);
            error = "whisper produced non-monotonic segment timing";
            segments.clear();
            return false;
        }
        std::string text(raw_text);
        if (text.empty()) {
            continue;
        }
        if (text.size() > 4000U) {
            whisper_free(context);
            error = "whisper segment text exceeds the safety limit";
            segments.clear();
            return false;
        }
        segments.push_back(WorkerSegment{start, end, std::move(text)});
        previous_start = start;
    }

    whisper_free(context);
    return true;
}
