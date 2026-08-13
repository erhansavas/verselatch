// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <string>
#include <vector>

bool verselatch_decode_audio(
    const std::string & path,
    std::vector<float> & pcm,
    std::string & error
);
