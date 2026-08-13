// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <string>

struct whisper_context;
struct whisper_context_params;

bool verselatch_model_integrity_self_test();

whisper_context * verselatch_load_verified_model(
    const std::string & model_path,
    const whisper_context_params & params,
    std::string & error
);
