from __future__ import annotations

import ctypes
import os
import subprocess
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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
    ) -> subprocess.Popen[str]:
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
    ) -> subprocess.Popen[str]:
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


class WindowsJobSandboxRunner(DirectSandboxRunner):
    @property
    def backend_name(self) -> str:
        return "windows_job_object"

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

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            process.kill()
            stdout, stderr = process.communicate()
            return SandboxExecutionResult(
                argv=tuple(argv),
                exit_code=None,
                stdout=stdout or str(error.stdout or ""),
                stderr=stderr or str(error.stderr or ""),
                timed_out=True,
                sandbox_mode=self.mode,
                sandbox_backend=self.backend_name,
                sandboxed=True,
                error_code="command_timeout",
                error_message="command timed out",
            )

        return SandboxExecutionResult(
            argv=tuple(argv),
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            sandbox_mode=self.mode,
            sandbox_backend=self.backend_name,
            sandboxed=True,
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
    ) -> subprocess.Popen[str]:
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

        job_handle = _create_restrictive_job_object()
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                env=dict(env) if env is not None else None,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            process_handle = getattr(process, "_handle", None)
            if not isinstance(process_handle, int):
                process.kill()
                raise SandboxUnavailableError("subprocess handle is unavailable")
            _assign_process_to_job(job_handle=job_handle, process_handle=process_handle)
        except Exception:
            _close_handle(job_handle)
            raise

        weakref.finalize(process, _close_handle, job_handle)
        return process


def build_sandbox_runner(*, mode: SandboxMode) -> SandboxRunner:
    if mode == SandboxMode.FULL_ACCESS:
        return DirectSandboxRunner(mode=mode)
    return WindowsJobSandboxRunner(mode=mode)


def _create_restrictive_job_object() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise SandboxUnavailableError(_last_windows_error("CreateJobObjectW"))

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
    )
    ok = kernel32.SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        message = _last_windows_error("SetInformationJobObject")
        _close_handle(handle)
        raise SandboxUnavailableError(message)
    return int(handle)


def _assign_process_to_job(*, job_handle: int, process_handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ok = kernel32.AssignProcessToJobObject(job_handle, process_handle)
    if not ok:
        raise SandboxUnavailableError(_last_windows_error("AssignProcessToJobObject"))


def _close_handle(handle: int) -> None:
    if not handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle(handle)


def _last_windows_error(function_name: str) -> str:
    error_code = ctypes.get_last_error()
    return f"{function_name} failed with Windows error {error_code}"


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
