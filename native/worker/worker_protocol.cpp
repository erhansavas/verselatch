// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "worker_protocol.h"

#include "yyjson.h"

#include <array>
#include <cstdlib>
#include <iostream>
#include <set>
#include <string_view>

namespace {
constexpr std::size_t kMaximumRequestBytes = 5U * 1024U * 1024U;
constexpr std::size_t kMaximumResourceRefChars = 4096U;
constexpr std::size_t kMaximumLanguageChars = 16U;
constexpr std::uint64_t kMaximumRequestId = (std::uint64_t{1} << 63U) - 1U;

bool has_nul(const std::string & value) {
    return value.find('\0') != std::string::npos;
}

bool read_string(yyjson_val * value, std::string & output) {
    if (!yyjson_is_str(value)) {
        return false;
    }
    const char * text = yyjson_get_str(value);
    const std::size_t length = yyjson_get_len(value);
    if (text == nullptr) {
        return false;
    }
    output.assign(text, length);
    return !has_nul(output);
}

bool exact_request_fields(yyjson_val * root) {
    static const std::set<std::string> expected{
        "audio_ref",
        "language",
        "lyrics",
        "model_ref",
        "protocol",
        "request_id",
        "type",
    };
    std::set<std::string> seen;
    yyjson_obj_iter iterator = yyjson_obj_iter_with(root);
    yyjson_val * key = nullptr;
    while ((key = yyjson_obj_iter_next(&iterator)) != nullptr) {
        const char * text = yyjson_get_str(key);
        const std::size_t length = yyjson_get_len(key);
        if (text == nullptr) {
            return false;
        }
        const std::string name(text, length);
        if (!seen.insert(name).second) {
            return false;
        }
    }
    return seen == expected;
}

void write_document(yyjson_mut_doc * doc) {
    std::size_t length = 0;
    char * json = yyjson_mut_write(doc, YYJSON_WRITE_NOFLAG, &length);
    if (json == nullptr) {
        return;
    }
    std::cout.write(json, static_cast<std::streamsize>(length));
    std::cout.put('\n');
    std::cout.flush();
    std::free(json);
}
}

bool worker_read_request(WorkerRequest & request, std::string & error) {
    request = WorkerRequest{};
    error.clear();

    std::string input;
    input.reserve(4096U);
    std::array<char, 64U * 1024U> buffer{};
    while (std::cin.good()) {
        std::cin.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const std::streamsize count = std::cin.gcount();
        if (count <= 0) {
            break;
        }
        if (input.size() + static_cast<std::size_t>(count) > kMaximumRequestBytes) {
            error = "worker request exceeds size limit";
            return false;
        }
        input.append(buffer.data(), static_cast<std::size_t>(count));
    }
    if (input.empty()) {
        error = "worker request is empty";
        return false;
    }

    yyjson_doc * doc = yyjson_read(input.data(), input.size(), YYJSON_READ_NOFLAG);
    if (doc == nullptr) {
        error = "worker request is not strict JSON";
        return false;
    }
    struct DocumentGuard {
        yyjson_doc * doc;
        ~DocumentGuard() { yyjson_doc_free(doc); }
    } guard{doc};

    yyjson_val * root = yyjson_doc_get_root(doc);
    if (!yyjson_is_obj(root)) {
        error = "worker request root must be an object";
        return false;
    }

    yyjson_val * request_id = yyjson_obj_get(root, "request_id");
    if (yyjson_is_uint(request_id)) {
        const std::uint64_t value = yyjson_get_uint(request_id);
        if (value > 0U && value <= kMaximumRequestId) {
            request.request_id = value;
        }
    }

    if (!exact_request_fields(root)) {
        error = "worker request fields are invalid or duplicated";
        return false;
    }

    yyjson_val * protocol = yyjson_obj_get(root, "protocol");
    yyjson_val * type = yyjson_obj_get(root, "type");
    yyjson_val * lyrics = yyjson_obj_get(root, "lyrics");
    if (!yyjson_is_uint(protocol) || yyjson_get_uint(protocol) != 1U) {
        error = "unsupported worker protocol version";
        return false;
    }
    if (!yyjson_is_str(type) || !yyjson_equals_str(type, "analyze")) {
        error = "worker request type must be analyze";
        return false;
    }
    if (request.request_id == 0U) {
        error = "worker request id is invalid";
        return false;
    }
    if (!yyjson_is_null(lyrics)) {
        error = "native evidence worker does not accept lyrics";
        return false;
    }

    if (!read_string(yyjson_obj_get(root, "audio_ref"), request.audio_ref)
        || request.audio_ref.empty()
        || request.audio_ref.size() > kMaximumResourceRefChars) {
        error = "audio reference is invalid";
        return false;
    }
    if (!read_string(yyjson_obj_get(root, "model_ref"), request.model_ref)
        || request.model_ref.empty()
        || request.model_ref.size() > kMaximumResourceRefChars) {
        error = "model reference is invalid";
        return false;
    }
    if (!read_string(yyjson_obj_get(root, "language"), request.language)
        || request.language.empty()
        || request.language.size() > kMaximumLanguageChars) {
        error = "language is invalid";
        return false;
    }

    return true;
}

void worker_write_error(
    std::uint64_t request_id,
    const char * code,
    const std::string & message
) {
    yyjson_mut_doc * doc = yyjson_mut_doc_new(nullptr);
    if (doc == nullptr) {
        return;
    }
    yyjson_mut_val * root = yyjson_mut_obj(doc);
    yyjson_mut_doc_set_root(doc, root);
    yyjson_mut_obj_add_uint(doc, root, "protocol", 1U);
    yyjson_mut_obj_add_uint(doc, root, "request_id", request_id);
    yyjson_mut_obj_add_strcpy(doc, root, "type", "error");
    yyjson_mut_obj_add_strcpy(doc, root, "code", code);
    yyjson_mut_obj_add_strncpy(doc, root, "message", message.data(), message.size());
    write_document(doc);
    yyjson_mut_doc_free(doc);
}

void worker_write_analysis(
    std::uint64_t request_id,
    const std::vector<WorkerSegment> & segments
) {
    yyjson_mut_doc * doc = yyjson_mut_doc_new(nullptr);
    if (doc == nullptr) {
        return;
    }
    yyjson_mut_val * root = yyjson_mut_obj(doc);
    yyjson_mut_val * payload = yyjson_mut_obj(doc);
    yyjson_mut_val * segment_array = yyjson_mut_arr(doc);
    yyjson_mut_val * rhythm = yyjson_mut_obj(doc);
    yyjson_mut_doc_set_root(doc, root);

    for (const WorkerSegment & segment : segments) {
        yyjson_mut_val * item = yyjson_mut_obj(doc);
        yyjson_mut_obj_add_real(doc, item, "start", segment.start);
        yyjson_mut_obj_add_real(doc, item, "end", segment.end);
        yyjson_mut_obj_add_strncpy(doc, item, "text", segment.text.data(), segment.text.size());
        yyjson_mut_arr_append(segment_array, item);
    }

    yyjson_mut_obj_add_val(doc, payload, "segments", segment_array);
    yyjson_mut_obj_add_val(doc, payload, "rhythm", rhythm);
    yyjson_mut_obj_add_uint(doc, root, "protocol", 1U);
    yyjson_mut_obj_add_uint(doc, root, "request_id", request_id);
    yyjson_mut_obj_add_strcpy(doc, root, "type", "analysis");
    yyjson_mut_obj_add_val(doc, root, "payload", payload);

    write_document(doc);
    yyjson_mut_doc_free(doc);
}
