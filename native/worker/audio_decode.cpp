// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "audio_decode.h"

#include "whisper.h"

#define STB_VORBIS_HEADER_ONLY
#include "stb_vorbis.c"

#define MA_NO_DEVICE_IO
#define MA_NO_THREADING
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#define MA_NO_RESOURCE_MANAGER
#define MA_NO_NODE_GRAPH
#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"

#undef STB_VORBIS_HEADER_ONLY
#include "stb_vorbis.c"

#include <cstdint>
#include <limits>

namespace {
constexpr std::uint64_t kMaximumAudioSeconds = 2U * 60U * 60U;
constexpr std::uint64_t kMaximumPcmFrames =
    static_cast<std::uint64_t>(WHISPER_SAMPLE_RATE) * kMaximumAudioSeconds;
}

bool verselatch_decode_audio(
    const std::string & path,
    std::vector<float> & pcm,
    std::string & error
) {
    pcm.clear();
    error.clear();

    ma_decoder_config config = ma_decoder_config_init(
        ma_format_f32,
        1,
        WHISPER_SAMPLE_RATE
    );
    ma_decoder decoder{};
    const ma_result init_result = ma_decoder_init_file(path.c_str(), &config, &decoder);
    if (init_result != MA_SUCCESS) {
        error = "unsupported, unreadable, or invalid audio input";
        return false;
    }

    struct DecoderGuard {
        ma_decoder * decoder;
        ~DecoderGuard() {
            ma_decoder_uninit(decoder);
        }
    } guard{&decoder};

    ma_uint64 frame_count = 0;
    const ma_result length_result = ma_decoder_get_length_in_pcm_frames(&decoder, &frame_count);
    if (length_result != MA_SUCCESS || frame_count == 0 || frame_count > kMaximumPcmFrames) {
        error = "decoded audio duration is invalid or exceeds the safety limit";
        return false;
    }
    if (frame_count > static_cast<ma_uint64>(std::numeric_limits<std::size_t>::max())) {
        error = "decoded audio is too large for this platform";
        return false;
    }

    try {
        pcm.resize(static_cast<std::size_t>(frame_count));
    } catch (...) {
        error = "decoded audio could not be allocated";
        pcm.clear();
        return false;
    }

    ma_uint64 frames_read = 0;
    const ma_result read_result = ma_decoder_read_pcm_frames(
        &decoder,
        pcm.data(),
        frame_count,
        &frames_read
    );
    if (read_result != MA_SUCCESS || frames_read == 0 || frames_read > frame_count) {
        error = "audio decoder failed while reading PCM frames";
        pcm.clear();
        return false;
    }

    pcm.resize(static_cast<std::size_t>(frames_read));
    return true;
}
