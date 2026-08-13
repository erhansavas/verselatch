# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

cmake_minimum_required(VERSION 3.20)
project(verselatch-native-worker VERSION 0.1.0 LANGUAGES C CXX)

include(FetchContent)

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(FETCHCONTENT_UPDATES_DISCONNECTED ON)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)

set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(WHISPER_CURL OFF CACHE BOOL "" FORCE)
set(WHISPER_SDL2 OFF CACHE BOOL "" FORCE)
set(WHISPER_COMMON_FFMPEG OFF CACHE BOOL "" FORCE)
set(YYJSON_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(YYJSON_BUILD_FUZZER OFF CACHE BOOL "" FORCE)
set(YYJSON_BUILD_MISC OFF CACHE BOOL "" FORCE)
set(YYJSON_BUILD_DOC OFF CACHE BOOL "" FORCE)
set(YYJSON_INSTALL OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    whisper
    GIT_REPOSITORY https://github.com/ggml-org/whisper.cpp.git
    GIT_TAG 23ee03506a91ac3d3f0071b40e66a430eebdfa1d
    GIT_SHALLOW FALSE
    GIT_PROGRESS FALSE
)
FetchContent_Declare(
    yyjson
    GIT_REPOSITORY https://github.com/ibireme/yyjson.git
    GIT_TAG 8b4a38dc994a110abaec8a400615567bd996105f
    GIT_SHALLOW FALSE
    GIT_PROGRESS FALSE
)
FetchContent_MakeAvailable(whisper yyjson)

add_executable(
    verselatch-worker
    main.cpp
    asr.cpp
    audio_decode.cpp
    worker_protocol.cpp
)
add_executable(
    verselatch-audio-smoke
    audio_smoke.cpp
    audio_decode.cpp
)

foreach(target verselatch-worker verselatch-audio-smoke)
    target_compile_features(${target} PRIVATE cxx_std_17)
    target_include_directories(
        ${target}
        PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}
            ${whisper_SOURCE_DIR}/examples
    )
    target_link_libraries(${target} PRIVATE whisper)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX /permissive-)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endforeach()

target_link_libraries(verselatch-worker PRIVATE yyjson)
