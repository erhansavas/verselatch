// SPDX-FileCopyrightText: 2026 erhansavas
// SPDX-License-Identifier: GPL-3.0-only

#include "model_loader.h"

#include "whisper.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>

class Sha256 final {
public:
    Sha256();
    void update(const void * data, std::size_t size);
    std::array<std::uint8_t, 32> finish();
    std::string finish_hex();

private:
    void transform(const std::uint8_t block[64]);

    std::array<std::uint32_t, 8> state_;
    std::array<std::uint8_t, 64> buffer_{};
    std::size_t buffer_size_ = 0;
    std::uint64_t total_bytes_ = 0;
    bool finished_ = false;
};

namespace {
constexpr std::array<std::uint32_t, 64> kRoundConstants{
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
    0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
    0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
    0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};

constexpr std::uint32_t rotate_right(std::uint32_t value, unsigned bits) {
    return (value >> bits) | (value << (32U - bits));
}

constexpr std::uint32_t choose(std::uint32_t x, std::uint32_t y, std::uint32_t z) {
    return (x & y) ^ (~x & z);
}

constexpr std::uint32_t majority(std::uint32_t x, std::uint32_t y, std::uint32_t z) {
    return (x & y) ^ (x & z) ^ (y & z);
}

constexpr std::uint32_t big_sigma0(std::uint32_t x) {
    return rotate_right(x, 2U) ^ rotate_right(x, 13U) ^ rotate_right(x, 22U);
}

constexpr std::uint32_t big_sigma1(std::uint32_t x) {
    return rotate_right(x, 6U) ^ rotate_right(x, 11U) ^ rotate_right(x, 25U);
}

constexpr std::uint32_t small_sigma0(std::uint32_t x) {
    return rotate_right(x, 7U) ^ rotate_right(x, 18U) ^ (x >> 3U);
}

constexpr std::uint32_t small_sigma1(std::uint32_t x) {
    return rotate_right(x, 17U) ^ rotate_right(x, 19U) ^ (x >> 10U);
}
}

Sha256::Sha256()
    : state_{
        0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
        0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
    } {}

void Sha256::transform(const std::uint8_t block[64]) {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t i = 0; i < 16; ++i) {
        const std::size_t offset = i * 4U;
        words[i] =
            (static_cast<std::uint32_t>(block[offset]) << 24U)
            | (static_cast<std::uint32_t>(block[offset + 1U]) << 16U)
            | (static_cast<std::uint32_t>(block[offset + 2U]) << 8U)
            | static_cast<std::uint32_t>(block[offset + 3U]);
    }
    for (std::size_t i = 16; i < words.size(); ++i) {
        words[i] = small_sigma1(words[i - 2U])
            + words[i - 7U]
            + small_sigma0(words[i - 15U])
            + words[i - 16U];
    }

    std::uint32_t a = state_[0];
    std::uint32_t b = state_[1];
    std::uint32_t c = state_[2];
    std::uint32_t d = state_[3];
    std::uint32_t e = state_[4];
    std::uint32_t f = state_[5];
    std::uint32_t g = state_[6];
    std::uint32_t h = state_[7];

    for (std::size_t i = 0; i < words.size(); ++i) {
        const std::uint32_t temp1 = h + big_sigma1(e) + choose(e, f, g)
            + kRoundConstants[i] + words[i];
        const std::uint32_t temp2 = big_sigma0(a) + majority(a, b, c);
        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
}

void Sha256::update(const void * data, std::size_t size) {
    if (finished_) {
        throw std::logic_error("SHA-256 context already finalized");
    }
    if (size == 0U) {
        return;
    }
    if (data == nullptr) {
        throw std::invalid_argument("SHA-256 input pointer is null");
    }
    if (size > (UINT64_MAX - total_bytes_)) {
        throw std::overflow_error("SHA-256 input length overflow");
    }

    const auto * bytes = static_cast<const std::uint8_t *>(data);
    total_bytes_ += static_cast<std::uint64_t>(size);

    while (size > 0U) {
        const std::size_t space = buffer_.size() - buffer_size_;
        const std::size_t take = std::min(space, size);
        std::copy_n(bytes, take, buffer_.data() + buffer_size_);
        buffer_size_ += take;
        bytes += take;
        size -= take;
        if (buffer_size_ == buffer_.size()) {
            transform(buffer_.data());
            buffer_size_ = 0U;
        }
    }
}

std::array<std::uint8_t, 32> Sha256::finish() {
    if (finished_) {
        throw std::logic_error("SHA-256 context already finalized");
    }
    if (total_bytes_ > UINT64_MAX / 8U) {
        throw std::overflow_error("SHA-256 bit length overflow");
    }
    const std::uint64_t bit_length = total_bytes_ * 8U;

    buffer_[buffer_size_++] = 0x80U;
    if (buffer_size_ > 56U) {
        std::fill(buffer_.begin() + static_cast<std::ptrdiff_t>(buffer_size_), buffer_.end(), 0U);
        transform(buffer_.data());
        buffer_size_ = 0U;
    }
    std::fill(
        buffer_.begin() + static_cast<std::ptrdiff_t>(buffer_size_),
        buffer_.begin() + 56,
        0U
    );
    for (std::size_t i = 0; i < 8U; ++i) {
        buffer_[63U - i] = static_cast<std::uint8_t>(bit_length >> (i * 8U));
    }
    transform(buffer_.data());
    buffer_size_ = 0U;
    finished_ = true;

    std::array<std::uint8_t, 32> digest{};
    for (std::size_t i = 0; i < state_.size(); ++i) {
        digest[i * 4U] = static_cast<std::uint8_t>(state_[i] >> 24U);
        digest[i * 4U + 1U] = static_cast<std::uint8_t>(state_[i] >> 16U);
        digest[i * 4U + 2U] = static_cast<std::uint8_t>(state_[i] >> 8U);
        digest[i * 4U + 3U] = static_cast<std::uint8_t>(state_[i]);
    }
    return digest;
}

std::string Sha256::finish_hex() {
    const auto digest = finish();
    std::ostringstream stream;
    stream << std::hex << std::setfill('0');
    for (const std::uint8_t byte : digest) {
        stream << std::setw(2) << static_cast<unsigned>(byte);
    }
    return stream.str();
}

bool verselatch_model_integrity_self_test() {
    auto digest = [](const std::string & input) {
        Sha256 hash;
        hash.update(input.data(), input.size());
        return hash.finish_hex();
    };
    return digest("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        && digest("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        && digest("The quick brown fox jumps over the lazy dog")
            == "d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592";
}


namespace {
std::filesystem::path utf8_path(const std::string & value) {
#if defined(__cpp_char8_t)
    std::u8string converted;
    converted.reserve(value.size());
    for (const unsigned char byte : value) {
        converted.push_back(static_cast<char8_t>(byte));
    }
    return std::filesystem::path(converted);
#else
    return std::filesystem::u8path(value);
#endif
}

constexpr const char * kExpectedModelName = "ggml-large-v3-turbo.bin";
constexpr std::uint64_t kExpectedModelSize = 1624555275ULL;
constexpr const char * kExpectedModelSha256 =
    "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69";

struct LoaderContext {
    std::ifstream stream;
    Sha256 digest;
    std::uint64_t bytes_read = 0U;
    bool io_error = false;
};

std::size_t loader_read(void * opaque, void * output, std::size_t requested) {
    auto * context = static_cast<LoaderContext *>(opaque);
    if (context == nullptr || output == nullptr || requested == 0U || context->io_error) {
        return 0U;
    }
    if (requested > static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max())) {
        context->io_error = true;
        return 0U;
    }

    if (context->bytes_read >= kExpectedModelSize) {
        std::memset(output, 0, requested);
        return 0U;
    }
    const std::uint64_t remaining = kExpectedModelSize - context->bytes_read;
    const std::size_t bounded = static_cast<std::size_t>(
        std::min<std::uint64_t>(remaining, static_cast<std::uint64_t>(requested))
    );

    context->stream.read(static_cast<char *>(output), static_cast<std::streamsize>(bounded));
    const std::streamsize count = context->stream.gcount();
    if (count < 0) {
        context->io_error = true;
        return 0U;
    }
    const auto actual = static_cast<std::size_t>(count);
    if (actual > 0U) {
        if (context->bytes_read > kExpectedModelSize
            || actual > kExpectedModelSize - context->bytes_read) {
            context->io_error = true;
            return 0U;
        }
        context->digest.update(output, actual);
        context->bytes_read += static_cast<std::uint64_t>(actual);
    }
    if (actual < requested) {
        std::memset(
            static_cast<char *>(output) + actual,
            0,
            requested - actual
        );
    }
    if (actual != bounded) {
        context->io_error = true;
    }
    return actual;
}

bool loader_eof(void * opaque) {
    const auto * context = static_cast<const LoaderContext *>(opaque);
    return context == nullptr
        || context->io_error
        || context->bytes_read >= kExpectedModelSize
        || context->stream.eof();
}

void loader_close(void *) {
    // The owning LoaderContext keeps this exact file handle alive until
    // post-load digest verification completes.
}

bool exact_model_file_size(std::ifstream & stream) {
    stream.seekg(0, std::ios::end);
    const std::streampos end = stream.tellg();
    if (end < 0 || static_cast<std::uint64_t>(end) != kExpectedModelSize) {
        return false;
    }
    stream.seekg(0, std::ios::beg);
    return stream.good();
}
}

whisper_context * verselatch_load_verified_model(
    const std::string & model_path,
    const whisper_context_params & params,
    std::string & error
) {
    error.clear();

    const std::filesystem::path path = utf8_path(model_path);
    if (path.filename() != utf8_path(kExpectedModelName)) {
        error = "model filename does not match the pinned VerseLatch model";
        return nullptr;
    }

    LoaderContext context;
    context.stream.open(path, std::ios::binary);
    if (!context.stream.is_open() || !exact_model_file_size(context.stream)) {
        error = "model size does not match the pinned VerseLatch model";
        return nullptr;
    }

    whisper_model_loader loader{};
    loader.context = &context;
    loader.read = loader_read;
    loader.eof = loader_eof;
    loader.close = loader_close;

    whisper_context * whisper = whisper_init_with_params(&loader, params);
    if (whisper == nullptr) {
        error = "model could not be loaded by whisper";
        return nullptr;
    }

    if (context.io_error
        || context.bytes_read != kExpectedModelSize
        || context.digest.finish_hex() != kExpectedModelSha256) {
        whisper_free(whisper);
        error = "model bytes do not match the pinned VerseLatch model";
        return nullptr;
    }

    return whisper;
}
