from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


class WindowsSandboxError(RuntimeError):
    pass


_kernel32: Any
_advapi32: Any


def _bind(func: Any, restype: Any, *argtypes: Any) -> Any:
    func.restype = restype
    func.argtypes = list(argtypes)
    return func


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
else:  # pragma: no cover - imported on non-Windows only for typing
    _kernel32 = None
    _advapi32 = None


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", wintypes.LPVOID),
        ("Attributes", wintypes.DWORD),
    ]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_ADJUST_GROUPS = 0x0040
TOKEN_ADJUST_DEFAULT = 0x0080

DISABLE_MAX_PRIVILEGE = 0x0001

SE_GROUP_INTEGRITY = 0x00000020

TOKEN_INTEGRITY_LEVEL = 25

HANDLE_FLAG_INHERIT = 0x00000001

SAFER_SCOPEID_MACHINE = 1
SAFER_LEVELID_CONSTRAINED = 0x00010000
SAFER_LEVEL_OPEN = 1
SAFER_TOKEN_MAKE_INERT = 0x00000004

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400


def create_restricted_primary_token() -> int:
    if os.name != "nt":
        raise WindowsSandboxError("windows restricted tokens are only available on Windows")
    base_token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(),
        TOKEN_DUPLICATE
        | TOKEN_QUERY
        | TOKEN_ADJUST_PRIVILEGES
        | TOKEN_ADJUST_GROUPS
        | TOKEN_ADJUST_DEFAULT,
        ctypes.byref(base_token),
    ):
        raise WindowsSandboxError(_last_windows_error("OpenProcessToken"))

    safer_level = wintypes.HANDLE()
    restricted_token = wintypes.HANDLE()
    try:
        if not _advapi32.SaferCreateLevel(
            SAFER_SCOPEID_MACHINE,
            SAFER_LEVELID_CONSTRAINED,
            SAFER_LEVEL_OPEN,
            ctypes.byref(safer_level),
            None,
        ):
            raise WindowsSandboxError(_last_windows_error("SaferCreateLevel"))

        restricted_token = wintypes.HANDLE()
        if not _advapi32.SaferComputeTokenFromLevel(
            safer_level,
            _handle_value(base_token),
            ctypes.byref(restricted_token),
            SAFER_TOKEN_MAKE_INERT,
            None,
        ):
            raise WindowsSandboxError(_last_windows_error("SaferComputeTokenFromLevel"))
        _set_low_integrity(restricted_token)
        if restricted_token.value is None:
            raise WindowsSandboxError("SaferComputeTokenFromLevel returned no token")
        return int(restricted_token.value)
    except BaseException:
        if restricted_token.value:
            close_handle(int(restricted_token.value))
        raise
    finally:
        if safer_level.value:
            _advapi32.SaferCloseLevel(safer_level)
        close_handle(_handle_value(base_token))


def create_job_object() -> int:
    if os.name != "nt":
        raise WindowsSandboxError("windows job objects are only available on Windows")
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise WindowsSandboxError(_last_windows_error("CreateJobObjectW"))

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
    )
    if not _kernel32.SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        message = _last_windows_error("SetInformationJobObject")
        close_handle(_handle_value(handle))
        raise WindowsSandboxError(message)
    return _handle_value(handle)


def assign_process_to_job_object(*, job_handle: int, process_handle: int) -> None:
    if os.name != "nt":
        raise WindowsSandboxError("windows job objects are only available on Windows")
    if not _kernel32.AssignProcessToJobObject(job_handle, process_handle):
        raise WindowsSandboxError(_last_windows_error("AssignProcessToJobObject"))


def terminate_job_object(job_handle: int, exit_code: int = 1) -> None:
    if os.name != "nt":
        raise WindowsSandboxError("windows job objects are only available on Windows")
    if not _kernel32.TerminateJobObject(job_handle, exit_code):
        raise WindowsSandboxError(_last_windows_error("TerminateJobObject"))


def set_handle_inheritable(handle: int, inheritable: bool) -> None:
    if os.name != "nt":
        raise WindowsSandboxError("windows handles are only available on Windows")
    flags = HANDLE_FLAG_INHERIT if inheritable else 0
    if not _kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, flags):
        raise WindowsSandboxError(_last_windows_error("SetHandleInformation"))


def close_handle(handle: int) -> None:
    if os.name != "nt" or not handle:
        return
    _kernel32.CloseHandle(handle)


def _set_low_integrity(token_handle: wintypes.HANDLE) -> None:
    token_handle_value = _handle_value(token_handle)
    sid = wintypes.LPVOID()
    if not _advapi32.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(sid)):
        raise WindowsSandboxError(_last_windows_error("ConvertStringSidToSidW"))
    try:
        sid_length = _advapi32.GetLengthSid(sid)
        total_size = ctypes.sizeof(TOKEN_MANDATORY_LABEL) + sid_length
        buffer = (ctypes.c_byte * total_size)()
        label_ptr = ctypes.cast(buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL))
        sid_target = ctypes.addressof(buffer) + ctypes.sizeof(TOKEN_MANDATORY_LABEL)
        ctypes.memmove(sid_target, sid, sid_length)
        label_ptr.contents.Label.Sid = ctypes.c_void_p(sid_target)
        label_ptr.contents.Label.Attributes = SE_GROUP_INTEGRITY
        if not _advapi32.SetTokenInformation(
            token_handle_value,
            TOKEN_INTEGRITY_LEVEL,
            ctypes.cast(buffer, wintypes.LPVOID),
            total_size,
        ):
            raise WindowsSandboxError(_last_windows_error("SetTokenInformation"))
    finally:
        if sid:
            _kernel32.LocalFree(sid)


def _handle_value(handle: object) -> int:
    if isinstance(handle, int):
        return handle
    value = getattr(handle, "value", None)
    if value is None:
        raise WindowsSandboxError("invalid Windows handle")
    return int(value)


def _last_windows_error(function_name: str) -> str:
    return f"{function_name} failed with Windows error {ctypes.get_last_error()}"


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


if os.name == "nt":
    _kernel32.GetCurrentProcess = _bind(
        _kernel32.GetCurrentProcess,
        ctypes.c_void_p,
    )
    _kernel32.CloseHandle = _bind(
        _kernel32.CloseHandle,
        wintypes.BOOL,
        ctypes.c_void_p,
    )
    _kernel32.SetHandleInformation = _bind(
        _kernel32.SetHandleInformation,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
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
        ctypes.c_int,
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
        ctypes.c_uint,
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
    _advapi32.CreateRestrictedToken.argtypes = None
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
    _advapi32.SaferCreateLevel = _bind(
        _advapi32.SaferCreateLevel,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    )
    _advapi32.SaferComputeTokenFromLevel = _bind(
        _advapi32.SaferComputeTokenFromLevel,
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    _advapi32.SaferCloseLevel = _bind(
        _advapi32.SaferCloseLevel,
        wintypes.BOOL,
        ctypes.c_void_p,
    )
