# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import BinaryIO

from verselatch_app import worker_protocol
from verselatch_app.backend import AnalysisEvidence, EvidenceBackend, EvidenceJob, EvidenceRequest
from verselatch_core.process import native_tool_env
from verselatch_core.storage import file_state_tuple, open_regular_readonly

from .posix_files import MAX_AUDIO_BYTES, PosixFileRevision


MAX_STDERR_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
CANCEL_GRACE_SECONDS = 0.50
PIPE_DRAIN_GRACE_SECONDS = 0.25
PIPE_JOIN_SECONDS = 1.0
SYSTEM_EXEC_PATH = "/usr/bin:/bin"
_ALLOWED_WORKER_NAMES = frozenset({"verselatch-worker"})


class PosixNativeBackendError(RuntimeError):
    """The package-owned POSIX native evidence worker failed safely."""


class PosixNativeBackendCancelled(PosixNativeBackendError):
    """The owned POSIX native evidence job was cancelled."""


@dataclass(frozen=True)
class _CapturedStream:
    data: bytes
    overflow: bool


def _read_bounded(
    stream: BinaryIO,
    limit: int,
    *,
    drain_overflow: bool = False,
) -> _CapturedStream:
    if limit < 0:
        raise ValueError("stream limit must be non-negative")

    chunks: list[bytes] = []
    total = 0
    overflow = False
    reader = getattr(stream, "read1", stream.read)

    try:
        while True:
            if total <= limit:
                request_size = min(READ_CHUNK_BYTES, limit + 1 - total)
            else:
                request_size = READ_CHUNK_BYTES

            chunk = reader(request_size)
            if not chunk:
                break

            if total < limit:
                keep = min(len(chunk), limit - total)
                if keep:
                    chunks.append(chunk[:keep])
                    total += keep
                if len(chunk) > keep:
                    overflow = True
            else:
                overflow = True

            if overflow and not drain_overflow:
                break
    finally:
        stream.close()

    return _CapturedStream(b"".join(chunks), overflow)


class _PosixNativeWorkerJob(EvidenceJob):
    def __init__(
        self,
        *,
        process: subprocess.Popen[bytes],
        request_bytes: bytes,
        request_id: int,
    ) -> None:
        self._process = process
        self._process_group = process.pid
        self._request_bytes = request_bytes
        self._request_id = request_id

        self._condition = threading.Condition()
        self._finished = False
        self._cancel_requested = False
        self._stop_started = False
        self._failure: BaseException | None = None
        self._returncode: int | None = None
        self._stdout = _CapturedStream(b"", False)
        self._stderr = _CapturedStream(b"", False)

        self._stdin_thread = threading.Thread(
            target=self._write_stdin,
            name=f"verselatch-worker-stdin-{request_id}",
            daemon=True,
        )
        self._stdout_thread = threading.Thread(
            target=self._capture_stdout,
            name=f"verselatch-worker-stdout-{request_id}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._capture_stderr,
            name=f"verselatch-worker-stderr-{request_id}",
            daemon=True,
        )
        self._wait_thread = threading.Thread(
            target=self._wait_and_finalize,
            name=f"verselatch-worker-wait-{request_id}",
            daemon=True,
        )

        self._stdin_thread.start()
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._wait_thread.start()

    def _record_failure(self, failure: BaseException) -> None:
        with self._condition:
            if self._failure is None:
                self._failure = failure

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self._process_group, sig)
        except ProcessLookupError:
            pass
        except OSError as exc:
            self._record_failure(
                PosixNativeBackendError("could not signal the native worker process group")
            )
            del exc

    def _request_stop(self) -> None:
        with self._condition:
            if self._stop_started or self._finished:
                return
            self._stop_started = True

        threading.Thread(
            target=self._terminate_then_kill_group,
            name=f"verselatch-worker-stop-{self._request_id}",
            daemon=True,
        ).start()

    def _terminate_then_kill_group(self) -> None:
        self._signal_group(signal.SIGTERM)
        try:
            self._process.wait(timeout=CANCEL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._signal_group(signal.SIGKILL)
            return

        # The direct worker may exit while a descendant still owns inherited
        # stdout/stderr descriptors. Keep the owned session from escaping.
        if self._stdout_thread.is_alive() or self._stderr_thread.is_alive():
            self._signal_group(signal.SIGKILL)

    def _write_stdin(self) -> None:
        stream = self._process.stdin
        if stream is None:
            self._record_failure(PosixNativeBackendError("native worker stdin pipe is unavailable"))
            self._request_stop()
            return

        try:
            stream.write(self._request_bytes)
            stream.flush()
        except (BrokenPipeError, OSError):
            self._record_failure(PosixNativeBackendError("native worker request pipe failed"))
            self._request_stop()
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _capture_stdout(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._record_failure(PosixNativeBackendError("native worker stdout pipe is unavailable"))
            self._request_stop()
            return

        try:
            captured = _read_bounded(stream, worker_protocol.MAX_RESPONSE_BYTES)
            self._stdout = captured
            if captured.overflow:
                self._record_failure(
                    PosixNativeBackendError("native worker response exceeded size limit")
                )
                self._request_stop()
        except OSError:
            self._record_failure(PosixNativeBackendError("native worker stdout read failed"))
            self._request_stop()

    def _capture_stderr(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return

        try:
            # Keep draining after the diagnostic capture cap so a verbose worker
            # cannot block on its stderr pipe while memory remains bounded.
            self._stderr = _read_bounded(
                stream,
                MAX_STDERR_BYTES,
                drain_overflow=True,
            )
        except OSError:
            self._stderr = _CapturedStream(b"", True)

    def _wait_and_finalize(self) -> None:
        try:
            self._returncode = self._process.wait()

            deadline = time.monotonic() + PIPE_DRAIN_GRACE_SECONDS
            for thread in (
                self._stdin_thread,
                self._stdout_thread,
                self._stderr_thread,
            ):
                remaining = max(0.0, deadline - time.monotonic())
                thread.join(remaining)

            io_threads = (
                self._stdin_thread,
                self._stdout_thread,
                self._stderr_thread,
            )
            if any(thread.is_alive() for thread in io_threads):
                # A descendant retained an inherited pipe after the direct
                # worker exited. Kill the owned session/process group so result()
                # cannot hang on an escaped child.
                self._signal_group(signal.SIGKILL)
                for thread in io_threads:
                    thread.join(PIPE_JOIN_SECONDS)

            if any(thread.is_alive() for thread in io_threads):
                self._record_failure(
                    PosixNativeBackendError("native worker pipes did not close after containment")
                )
        except BaseException as exc:
            self._record_failure(
                PosixNativeBackendError("native worker supervisor wait failed")
            )
            del exc
        finally:
            with self._condition:
                self._finished = True
                self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            if self._finished:
                return
            self._cancel_requested = True
        self._request_stop()

    def result(self, timeout: float | None = None) -> AnalysisEvidence:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative or None")

        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while not self._finished:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("native evidence job is still running")
                self._condition.wait(remaining)

            cancelled = self._cancel_requested
            failure = self._failure
            stdout = self._stdout
            returncode = self._returncode

        if cancelled:
            raise PosixNativeBackendCancelled("native evidence job was cancelled")
        if failure is not None:
            if isinstance(failure, PosixNativeBackendError):
                raise failure
            raise PosixNativeBackendError("native worker supervisor failed") from failure
        if stdout.overflow:
            raise PosixNativeBackendError("native worker response exceeded size limit")

        try:
            response = worker_protocol.decode_response(
                stdout.data,
                expected_request_id=self._request_id,
            )
        except worker_protocol.WorkerProtocolError as exc:
            raise PosixNativeBackendError("native worker returned an invalid response") from exc

        if response.error_code is not None:
            if response.error_code == "CANCELLED":
                raise PosixNativeBackendCancelled("native evidence worker reported cancellation")
            raise PosixNativeBackendError(
                f"native worker failed safely: {response.error_code}: {response.error_message}"
            )

        if returncode != 0:
            raise PosixNativeBackendError("native worker exited unsuccessfully after success")
        if response.payload is None:
            raise PosixNativeBackendError("native worker success response has no payload")

        rhythm = response.payload["rhythm"]
        assert isinstance(rhythm, dict)
        return AnalysisEvidence(
            segments=tuple(response.payload["segments"]),
            beats=tuple(rhythm.get("beats", ())),
            onsets=tuple(rhythm.get("onsets", ())),
        )


def _fd_reference(descriptor: int) -> str:
    for root in (Path("/dev/fd"), Path("/proc/self/fd")):
        if root.is_dir():
            return str(root / str(descriptor))
    raise PosixNativeBackendError(
        "this POSIX platform does not expose inherited file descriptors by path"
    )


def _open_verified_audio(source) -> int:
    revision = source.revision
    if not isinstance(revision, PosixFileRevision) or revision.kind != "audio":
        raise PosixNativeBackendError(
            "native worker requires a POSIX-verified audio source identity"
        )

    path = Path(source.location)
    if not path.is_absolute():
        raise PosixNativeBackendError("native audio source path must be absolute")

    descriptor = -1
    try:
        descriptor, metadata = open_regular_readonly(
            path,
            description="Audio source",
            maximum_bytes=MAX_AUDIO_BYTES,
        )
        if file_state_tuple(metadata) != revision.state:
            raise PosixNativeBackendError(
                "audio source changed before the native worker was started"
            )
        return descriptor
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _revalidate_model_source(request: EvidenceRequest) -> None:
    revision = request.model.source.revision
    if not isinstance(revision, PosixFileRevision) or revision.kind != "model":
        raise PosixNativeBackendError(
            "native worker requires a POSIX-verified model source identity"
        )

    path = Path(request.model.source.location)
    if not path.is_absolute():
        raise PosixNativeBackendError("native model source path must be absolute")

    descriptor = -1
    try:
        descriptor, metadata = open_regular_readonly(
            path,
            description="ASR model",
        )
        if file_state_tuple(metadata) != revision.state:
            raise PosixNativeBackendError(
                "ASR model changed after verification"
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class PosixNativeWorkerBackend(EvidenceBackend):
    """Launch one fixed-name VerseLatch POSIX worker in an owned process group."""

    def __init__(self, worker_path: str) -> None:
        if os.name != "posix":
            raise RuntimeError("POSIX native worker backend is unavailable on this platform")

        path = Path(worker_path)
        if not path.is_absolute():
            raise ValueError("native worker path must be absolute")
        if path.name not in _ALLOWED_WORKER_NAMES:
            raise ValueError("native worker path has an unexpected executable name")
        if path.is_symlink() or not path.is_file():
            raise ValueError("native worker path must be an existing non-symlink regular file")
        if not os.access(path, os.X_OK):
            raise ValueError("native worker path must be executable")

        self._worker_path = path
        self._lock = threading.Lock()
        self._next_request_id = 1

    def _allocate_request_id(self) -> int:
        with self._lock:
            request_id = self._next_request_id
            if request_id >= 2**63:
                raise PosixNativeBackendError("native worker request id space is exhausted")
            self._next_request_id += 1
            return request_id

    def start(self, request: EvidenceRequest) -> EvidenceJob:
        request_id = self._allocate_request_id()
        _revalidate_model_source(request)

        audio_descriptor = _open_verified_audio(request.audio)
        try:
            encoded = worker_protocol.encode_request(
                worker_protocol.WorkerRequest(
                    request_id=request_id,
                    audio_ref=_fd_reference(audio_descriptor),
                    model_ref=request.model.source.location,
                    language=request.language,
                    lyrics=None,
                )
            )

            try:
                process = subprocess.Popen(  # nosec B603
                    [str(self._worker_path)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    close_fds=True,
                    pass_fds=(audio_descriptor,),
                    start_new_session=True,
                    env=native_tool_env(system_path=SYSTEM_EXEC_PATH),
                )
            except OSError as exc:
                raise PosixNativeBackendError(
                    "could not start the package-owned native worker"
                ) from exc
        finally:
            os.close(audio_descriptor)

        return _PosixNativeWorkerJob(
            process=process,
            request_bytes=encoded,
            request_id=request_id,
        )
