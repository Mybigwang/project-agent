from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import weakref
from collections.abc import Mapping, Sequence
from contextlib import suppress
from ctypes import wintypes
from pathlib import Path
from typing import IO, Any

from project_agent.runtime.windows_security import (
    SECURITY_ATTRIBUTES,
    WindowsSandboxError,
    close_handle,
    set_handle_inheritable,
)

_kernel32: Any
_advapi32: Any
_msvcrt: Any

if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    import msvcrt as _msvcrt
else:  # pragma: no cover - imported on non-Windows only for typing
    _kernel32 = None
    _advapi32 = None
    _msvcrt = None


class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32),
        ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32),
        ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32),
        ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_uint16),
        ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32),
        ("dwThreadId", ctypes.c_uint32),
    ]


class WindowsSandboxProcess:
    def __init__(
        self,
        *,
        argv: Sequence[str],
        command_line: str,
        process_handle: int,
        thread_handle: int,
        stdin: IO[str] | None,
        stdout: IO[str] | None,
        stderr: IO[str] | None,
        job_handle: int | None = None,
    ) -> None:
        self.argv = tuple(argv)
        self.command_line = command_line
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = None
        self.process_handle = process_handle
        self._thread_handle = thread_handle
        self._job_handle = job_handle
        self._finalizer = weakref.finalize(
            self,
            _finalize_windows_process,
            process_handle,
            thread_handle,
            job_handle,
            stdin,
            stdout,
            stderr,
        )

    def own_job_handle(self, job_handle: int) -> None:
        self._job_handle = job_handle

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        if os.name != "nt":
            return None
        exit_code = ctypes.c_uint32()
        if not _kernel32.GetExitCodeProcess(self.process_handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value == _STILL_ACTIVE:
            return None
        self.returncode = int(exit_code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        if os.name != "nt":
            raise WindowsSandboxError("windows process wait is only available on Windows")
        result = _kernel32.WaitForSingleObject(
            self.process_handle, _timeout_to_milliseconds(timeout)
        )
        if result == _WAIT_OBJECT_0:
            exit_code = ctypes.c_uint32()
            if not _kernel32.GetExitCodeProcess(
                self.process_handle, ctypes.byref(exit_code)
            ):
                raise WindowsSandboxError(_last_windows_error("GetExitCodeProcess"))
            self.returncode = int(exit_code.value)
            return self.returncode
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.argv, 0.0 if timeout is None else timeout)
        raise WindowsSandboxError(_last_windows_error("WaitForSingleObject"))

    def terminate(self) -> None:
        if os.name != "nt":
            raise WindowsSandboxError("windows process terminate is only available on Windows")
        if self._job_handle:
            if not _kernel32.TerminateJobObject(self._job_handle, 1):
                raise WindowsSandboxError(_last_windows_error("TerminateJobObject"))
            close_handle(self._job_handle)
            self._job_handle = None
            return
        if not _kernel32.TerminateProcess(self.process_handle, 1):
            raise WindowsSandboxError(_last_windows_error("TerminateProcess"))

    def kill(self) -> None:
        self.terminate()


def launch_windows_process(
    *,
    token_handle: int,
    job_handle: int | None,
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None,
    stdin: int | None,
    stdout: int | None,
    stderr: int | None,
) -> WindowsSandboxProcess:
    if os.name != "nt":
        raise WindowsSandboxError("windows sandbox is only available on Windows")

    command_argv = _wrap_command_if_needed(argv)
    command_line = subprocess.list2cmdline(list(command_argv))
    command_line_buffer = ctypes.create_unicode_buffer(command_line)
    application_name = _resolve_application_name(command_argv[0])

    startup_info = STARTUPINFO()
    startup_info.cb = ctypes.sizeof(STARTUPINFO)
    startup_info.dwFlags = _STARTF_USESTDHANDLES

    stdin_parent, stdin_child = _create_std_handle(stdin, read_end=False)
    stdout_parent, stdout_child = _create_std_handle(stdout, read_end=True)
    stderr_parent, stderr_child = _create_std_handle(stderr, read_end=True)

    startup_info.hStdInput = stdin_child if stdin_child is not None else _default_std_handle(
        _STD_INPUT_HANDLE
    )
    startup_info.hStdOutput = stdout_child if stdout_child is not None else _default_std_handle(
        _STD_OUTPUT_HANDLE
    )
    startup_info.hStdError = stderr_child if stderr_child is not None else _default_std_handle(
        _STD_ERROR_HANDLE
    )

    process_info = PROCESS_INFORMATION()
    environment_block = _build_environment_block(env)
    creation_flags = _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
    if environment_block is not None:
        creation_flags |= _CREATE_UNICODE_ENVIRONMENT

    process_created = False
    launch_succeeded = False
    try:
        ok = _advapi32.CreateProcessAsUserW(
            token_handle,
            application_name,
            ctypes.cast(command_line_buffer, ctypes.c_void_p),
            None,
            None,
            True,
            creation_flags,
            environment_block,
            str(cwd),
            ctypes.byref(startup_info),
            ctypes.byref(process_info),
        )
        if not ok:
            raise WindowsSandboxError(_last_windows_error("CreateProcessAsUserW"))
        process_created = True
        if job_handle is not None and not _kernel32.AssignProcessToJobObject(
            job_handle, process_info.hProcess
        ):
            raise WindowsSandboxError(_last_windows_error("AssignProcessToJobObject"))
        launch_succeeded = True
    except BaseException:
        if process_created:
            with suppress(BaseException):
                _kernel32.TerminateProcess(process_info.hProcess, 1)
        raise
    finally:
        if stdin_child is not None:
            close_handle(stdin_child)
        if stdout_child is not None:
            close_handle(stdout_child)
        if stderr_child is not None:
            close_handle(stderr_child)
        close_handle(token_handle)
        if process_created and not launch_succeeded:
            close_handle(_handle_value(process_info.hThread))
            close_handle(_handle_value(process_info.hProcess))

    return WindowsSandboxProcess(
        argv=argv,
        command_line=command_line,
        process_handle=_handle_value(process_info.hProcess),
        thread_handle=_handle_value(process_info.hThread),
        stdin=stdin_parent,
        stdout=stdout_parent,
        stderr=stderr_parent,
        job_handle=job_handle,
    )


def _create_std_handle(
    std_handle: int | None,
    *,
    read_end: bool,
) -> tuple[IO[str] | None, int | None]:
    if std_handle == subprocess.PIPE:
        read_handle, write_handle = _create_pipe()
        parent_handle = read_handle if read_end else write_handle
        child_handle = write_handle if read_end else read_handle
        set_handle_inheritable(child_handle, True)
        set_handle_inheritable(parent_handle, False)
        if read_end:
            return _fd_to_text_reader(parent_handle), child_handle
        return _fd_to_text_writer(parent_handle), child_handle
    if std_handle == subprocess.DEVNULL:
        devnull_handle = _open_devnull_handle(read_end=read_end)
        set_handle_inheritable(devnull_handle, True)
        return None, devnull_handle
    if std_handle is None:
        return None, None
    raise WindowsSandboxError("unsupported standard handle type")


def _create_pipe() -> tuple[int, int]:
    read_handle = ctypes.c_void_p()
    write_handle = ctypes.c_void_p()
    security_attributes = SECURITY_ATTRIBUTES()
    security_attributes.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    security_attributes.bInheritHandle = True
    if not _kernel32.CreatePipe(
        ctypes.byref(read_handle),
        ctypes.byref(write_handle),
        ctypes.byref(security_attributes),
        0,
    ):
        raise WindowsSandboxError(_last_windows_error("CreatePipe"))
    return _handle_value(read_handle), _handle_value(write_handle)


def _build_environment_block(env: Mapping[str, str] | None) -> ctypes.Array[ctypes.c_wchar] | None:
    if env is None:
        return None
    items = sorted(env.items(), key=lambda item: item[0].casefold())
    block = "\x00".join(f"{key}={value}" for key, value in items) + "\x00\x00"
    return ctypes.create_unicode_buffer(block)


def _wrap_command_if_needed(argv: Sequence[str]) -> Sequence[str]:
    if not argv:
        raise WindowsSandboxError("argv cannot be empty")
    command = argv[0]
    lowered = command.lower()
    if lowered.endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
        return (comspec, "/d", "/s", "/c", subprocess.list2cmdline(list(argv)))
    return argv


def _resolve_application_name(command: str) -> str | None:
    if os.path.isabs(command) or os.sep in command:
        return os.path.normpath(command)
    if os.altsep is not None and os.altsep in command:
        return os.path.normpath(command)
    resolved = shutil.which(command)
    return os.path.normpath(resolved) if resolved is not None else None


def _fd_to_text_reader(handle: int) -> IO[str]:
    fd = _msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_TEXT)
    return os.fdopen(fd, "r", encoding="utf-8", errors="replace", newline="")


def _fd_to_text_writer(handle: int) -> IO[str]:
    fd = _msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_TEXT)
    return os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="", buffering=1)


def _fd_to_text_reader_from_fd(fd: int) -> IO[str]:
    return os.fdopen(fd, "r", encoding="utf-8", errors="replace", newline="")


def _fd_to_text_writer_from_fd(fd: int) -> IO[str]:
    return os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="", buffering=1)


def _open_devnull_handle(*, read_end: bool) -> int:
    access = _GENERIC_READ if read_end else _GENERIC_WRITE
    handle = _kernel32.CreateFileW(
        "NUL",
        access,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if not handle:
        raise WindowsSandboxError(_last_windows_error("CreateFileW"))
    return _handle_value(handle)


def _default_std_handle(which: int) -> int:
    handle = _kernel32.GetStdHandle(which)
    return _handle_value(handle)


def _finalize_windows_process(
    process_handle: int,
    thread_handle: int,
    job_handle: int | None,
    stdin: IO[str] | None,
    stdout: IO[str] | None,
    stderr: IO[str] | None,
) -> None:
    for stream in (stdin, stdout, stderr):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
    close_handle(thread_handle)
    close_handle(process_handle)
    if job_handle is not None:
        close_handle(job_handle)


def _timeout_to_milliseconds(timeout: float | None) -> int:
    if timeout is None:
        return _INFINITE
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
    return max(1, int(timeout * 1000))


def _handle_value(handle: object) -> int:
    if isinstance(handle, int):
        return handle
    value = getattr(handle, "value", None)
    if value is None:
        raise WindowsSandboxError("invalid Windows handle")
    return int(value)


def _last_windows_error(function_name: str) -> str:
    return f"{function_name} failed with Windows error {ctypes.get_last_error()}"


def _bind(func: Any, restype: Any, *argtypes: Any) -> Any:
    func.restype = restype
    func.argtypes = list(argtypes)
    return func


if os.name == "nt":
    _kernel32.GetExitCodeProcess = _bind(
        _kernel32.GetExitCodeProcess,
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    )
    _kernel32.GetStdHandle = _bind(
        _kernel32.GetStdHandle,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    _kernel32.WaitForSingleObject = _bind(
        _kernel32.WaitForSingleObject,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    _kernel32.TerminateProcess = _bind(
        _kernel32.TerminateProcess,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.UINT,
    )
    _kernel32.CreatePipe = _bind(
        _kernel32.CreatePipe,
        wintypes.BOOL,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(SECURITY_ATTRIBUTES),
        wintypes.DWORD,
    )
    _kernel32.CreateFileW = _bind(
        _kernel32.CreateFileW,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    _kernel32.CreateProcessAsUserW = _bind(
        _kernel32.CreateProcessAsUserW,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    _kernel32.CreateJobObjectW = _bind(
        _kernel32.CreateJobObjectW,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
    )
    _kernel32.SetInformationJobObject = _bind(
        _kernel32.SetInformationJobObject,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.INT,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    _kernel32.AssignProcessToJobObject = _bind(
        _kernel32.AssignProcessToJobObject,
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    _kernel32.TerminateJobObject = _bind(
        _kernel32.TerminateJobObject,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.UINT,
    )
    _kernel32.SetHandleInformation = _bind(
        _kernel32.SetHandleInformation,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _kernel32.CloseHandle = _bind(
        _kernel32.CloseHandle,
        wintypes.BOOL,
        ctypes.c_void_p,
    )
    _kernel32.GetCurrentProcess = _bind(
        _kernel32.GetCurrentProcess,
        ctypes.c_void_p,
    )
    _kernel32.LocalFree = _bind(_kernel32.LocalFree, ctypes.c_void_p, ctypes.c_void_p)
    _advapi32.OpenProcessToken = _bind(
        _advapi32.OpenProcessToken,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    _advapi32.CreateRestrictedToken = _bind(
        _advapi32.CreateRestrictedToken,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    _advapi32.SetTokenInformation = _bind(
        _advapi32.SetTokenInformation,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    _advapi32.ConvertStringSidToSidW = _bind(
        _advapi32.ConvertStringSidToSidW,
        wintypes.BOOL,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    )
    _advapi32.GetLengthSid = _bind(
        _advapi32.GetLengthSid,
        wintypes.DWORD,
        ctypes.c_void_p,
    )


_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_INFINITE = 0xFFFFFFFF
_STILL_ACTIVE = 259
_STARTF_USESTDHANDLES = 0x00000100
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NO_WINDOW = 0x08000000
_STD_INPUT_HANDLE = -10
_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
