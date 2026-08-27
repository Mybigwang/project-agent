from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, Protocol

from project_agent.runtime.windows_process import launch_windows_process
from project_agent.runtime.windows_security import (
    WindowsSandboxError,
    close_handle,
    create_job_object,
    create_restricted_primary_token,
)


class SandboxMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


@dataclass(frozen=True)
class SandboxExecutionResult:
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    sandbox_mode: SandboxMode
    sandbox_backend: str
    sandboxed: bool
    error_code: str | None = None
    error_message: str | None = None
    error_type: str | None = None


class SandboxError(Exception):
    pass


class SandboxUnavailableError(SandboxError):
    pass


class SandboxExecutionError(SandboxError):
    pass


class SandboxProcess(Protocol):
    stdin: IO[str] | None
    stdout: IO[str] | None
    stderr: IO[str] | None
    returncode: int | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class SandboxRunner:
    def __init__(self, *, mode: SandboxMode) -> None:
        self._mode = mode

    @property
    def mode(self) -> SandboxMode:
        return self._mode

    @property
    def backend_name(self) -> str:
        raise NotImplementedError

    @property
    def sandboxed(self) -> bool:
        raise NotImplementedError

    def run(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> SandboxExecutionResult:
        raise NotImplementedError

    def popen(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> SandboxProcess:
        raise NotImplementedError


class DirectSandboxRunner(SandboxRunner):
    @property
    def backend_name(self) -> str:
        return "direct"

    @property
    def sandboxed(self) -> bool:
        return False

    def run(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> SandboxExecutionResult:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
                check=False,
                env=dict(env) if env is not None else None,
            )
        except subprocess.TimeoutExpired as error:
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout=str(error.stdout or ""),
                stderr=str(error.stderr or ""),
                timed_out=True,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=self.sandboxed,
                error_code="command_timeout",
                error_message="command timed out",
            )
        except OSError as error:
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=self.sandboxed,
                error_code="command_execution_failed",
                error_message=str(error),
                error_type=type(error).__name__,
            )

        return SandboxExecutionResult(
            argv=tuple(argv),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            sandbox_mode=self.mode,
            sandbox_backend=self.backend_name,
            sandboxed=self.sandboxed,
        )

    def popen(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> SandboxProcess:
        return subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            env=dict(env) if env is not None else None,
        )


class WindowsRestrictedSandboxRunner(DirectSandboxRunner):
    @property
    def backend_name(self) -> str:
        return "windows_restricted_token"

    @property
    def sandboxed(self) -> bool:
        return self.mode != SandboxMode.FULL_ACCESS

    def run(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> SandboxExecutionResult:
        if self.mode == SandboxMode.FULL_ACCESS:
            return DirectSandboxRunner(mode=self.mode).run(
                argv=argv,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                env=env,
            )

        try:
            process = self.popen(
                argv=argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except SandboxError as error:
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=False,
                error_code="sandbox_failed",
                error_message=str(error),
                error_type=type(error).__name__,
            )
        except OSError as error:
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=False,
                error_code="command_execution_failed",
                error_message=str(error),
                error_type=type(error).__name__,
            )

        stdout_chunks: list[str] = [""]
        stderr_chunks: list[str] = [""]
        errors: list[BaseException] = []

        def read_stream(stream: IO[str] | None, target: list[str]) -> None:
            if stream is None:
                return
            try:
                target[0] = stream.read()
            except BaseException as error:  # pragma: no cover - defensive
                errors.append(error)

        stdout_reader = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout_chunks),
            daemon=True,
        )
        stderr_reader = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_chunks),
            daemon=True,
        )
        stdout_reader.start()
        stderr_reader.start()

        if process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()

        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            with suppress(OSError):
                process.kill()
            process.wait()
        except OSError as error:
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=False,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=True,
                error_code="command_execution_failed",
                error_message=str(error),
                error_type=type(error).__name__,
            )
        finally:
            stdout_reader.join()
            stderr_reader.join()

        if errors:
            stream_error = errors[0]
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout="",
                stderr="",
                timed_out=timed_out,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=True,
                error_code="command_execution_failed",
                error_message=str(stream_error),
                error_type=type(stream_error).__name__,
            )

        return SandboxExecutionResult(
            argv=tuple(argv),
            exit_code=None if timed_out else process.returncode,
            stdout=stdout_chunks[0],
            stderr=stderr_chunks[0],
            timed_out=timed_out,
            sandbox_mode=self.mode,
            sandbox_backend=self.backend_name,
            sandboxed=True,
            error_code="command_timeout" if timed_out else None,
            error_message="command timed out" if timed_out else None,
        )

    def popen(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> SandboxProcess:
        if self.mode == SandboxMode.FULL_ACCESS:
            return DirectSandboxRunner(mode=self.mode).popen(
                argv=argv,
                cwd=cwd,
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
        if os.name != "nt":
            raise SandboxUnavailableError("windows sandbox is only available on Windows")

        job_handle: int | None = None
        try:
            job_handle = create_job_object()
            process = launch_windows_process(
                token_handle=create_restricted_primary_token(),
                job_handle=job_handle,
                argv=argv,
                cwd=cwd,
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
            job_handle = None
            return process
        except WindowsSandboxError as error:
            raise SandboxUnavailableError(str(error)) from error
        finally:
            if job_handle is not None:
                close_handle(job_handle)


def build_sandbox_runner(*, mode: SandboxMode) -> SandboxRunner:
    if mode == SandboxMode.FULL_ACCESS:
        return DirectSandboxRunner(mode=mode)
    return WindowsRestrictedSandboxRunner(mode=mode)
