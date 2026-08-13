# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "native" / "worker"


def worker_text_files() -> list[Path]:
    return sorted(
        path
        for path in WORKER.iterdir()
        if path.is_file() and path.suffix in {".cpp", ".h", ".txt"}
    )


def test_native_worker_build_is_immutable_and_network_free_at_runtime() -> None:
    cmake = (WORKER / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "23ee03506a91ac3d3f0071b40e66a430eebdfa1d" in cmake
    assert "8b4a38dc994a110abaec8a400615567bd996105f" in cmake
    assert "WHISPER_CURL OFF" in cmake
    assert "WHISPER_COMMON_FFMPEG OFF" in cmake
    assert "BUILD_SHARED_LIBS OFF" in cmake
    assert "GIT_TAG master" not in cmake
    assert "GIT_TAG main" not in cmake


def test_native_worker_has_no_shell_network_or_child_process_surface() -> None:
    forbidden = (
        "system(",
        "std::system",
        "popen(",
        "fork(",
        "execve(",
        "CreateProcess",
        "ShellExecute",
        "WinExec",
        "curl_easy",
        "<sys/socket.h>",
        "<winsock",
    )
    for path in worker_text_files():
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"forbidden native runtime surface {token!r} in {path.name}"


def test_native_worker_source_hygiene_and_spdx() -> None:
    license_marker = "SPDX-" + "License-Identifier: GPL-3.0-only"
    for path in worker_text_files():
        data = path.read_bytes()
        assert b"\r\n" not in data, path.name
        text = data.decode("utf-8")
        head = "\n".join(text.splitlines()[:5])
        assert license_marker in head, path.name
        for number, line in enumerate(text.splitlines(), start=1):
            assert not line.endswith((" ", "\t")), f"trailing whitespace {path.name}:{number}"


def test_worker_remains_evidence_only() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in worker_text_files())
    for forbidden in (
        "align_lyrics",
        "render_lrc",
        "save_reviewed_lrc",
        ".lrc",
    ):
        assert forbidden not in combined
    protocol = (WORKER / "worker_protocol.cpp").read_text(encoding="utf-8")
    assert '"rhythm"' in protocol
    assert '"segments"' in protocol


def test_native_model_identity_matches_linux_installer() -> None:
    loader = (WORKER / "model_loader.cpp").read_text(encoding="utf-8")
    installer = (ROOT / "packaging" / "linux" / "install-model.sh").read_text(encoding="utf-8")
    expected = (
        "ggml-large-v3-turbo.bin",
        "1624555275",
        "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69",
    )
    for value in expected:
        assert value in loader
        assert value in installer
    assert "whisper_init_with_params(&loader, params)" in loader
    main = (WORKER / "main.cpp").read_text(encoding="utf-8")
    assert "verselatch_model_integrity_self_test()" in main
