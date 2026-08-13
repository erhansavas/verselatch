// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "audio_decode.h"

#include <iostream>
#include <string>
#include <vector>

int main(int argc, char ** argv) {
    if (argc != 2 || argv[1] == nullptr || std::string(argv[1]).empty()) {
        std::cerr << "usage: verselatch-audio-smoke FILE\n";
        return 2;
    }

    std::vector<float> pcm;
    std::string error;
    if (!verselatch_decode_audio(argv[1], pcm, error)) {
        std::cerr << error << '\n';
        return 1;
    }
    if (pcm.size() < 8000U || pcm.size() > 24000U) {
        std::cerr << "unexpected decoded frame count: " << pcm.size() << '\n';
        return 1;
    }

    std::cout << pcm.size() << '\n';
    return 0;
}
