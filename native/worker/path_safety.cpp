// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "path_safety.h"

#include <filesystem>

bool verselatch_safe_regular_path(const std::string & value) {
    const std::filesystem::path path(value);
    if (!path.is_absolute()) {
        return false;
    }

    std::error_code error;
    const std::filesystem::file_status status = std::filesystem::symlink_status(path, error);
    if (error || std::filesystem::is_symlink(status)) {
        return false;
    }
    return std::filesystem::is_regular_file(status);
}
