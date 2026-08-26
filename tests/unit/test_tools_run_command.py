from __future__ import annotations

import sys
from pathlib import Path

from project_agent.runtime.local_tools.command import RunCommandTool
from project_agent.runtime.sandbox import SandboxExecutionResult, SandboxMode


def test_run_command_executes_argv_in_workspace(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=5, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": [sys.executable, "-c", "import os; print(os.getcwd())"]},
    )

    assert result.is_error is False
    assert result.data == {
        "argv": [sys.executable, "-c", "import os; print(os.getcwd())"],
        "exit_code": 0,
        "stdout": str(tmp_path),
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 5,
        "sandbox_mode": "full_access",
        "sandbox_backend": "direct",
        "sandboxed": False,
    }


def test_run_command_returns_timeout_error(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import time; time.sleep(0.2)"]

    result = RunCommandTool(timeout_seconds=0.01, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": argv},
    )

    assert result.is_error is True
    assert result.error_code == "command_timeout"
    assert result.content == "command timed out; inspect data.argv and data.timeout_seconds"
    assert result.data == {
        "argv": argv,
        "timeout_seconds": 0.01,
        "sandbox_mode": "full_access",
        "sandbox_backend": "direct",
        "sandboxed": False,
    }


def test_run_command_truncates_output(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=5, max_output_chars=5).run(
        workspace_root=tmp_path,
        arguments={"argv": [sys.executable, "-c", "print('abcdefghij')"]},
    )

    assert result.is_error is False
    assert result.data == {
        "argv": [sys.executable, "-c", "print('abcdefghij')"],
        "exit_code": 0,
        "stdout": "abcde",
        "stderr": "",
        "stdout_truncated": True,
        "stderr_truncated": False,
        "timeout_seconds": 5,
        "sandbox_mode": "full_access",
        "sandbox_backend": "direct",
        "sandboxed": False,
    }


def test_run_command_marks_non_zero_exit_as_error(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=5, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": [sys.executable, "-c", "import sys; sys.exit(3)"]},
    )

    assert result.is_error is True
    assert result.error_code == "command_failed"
    assert result.content == "command failed with exit code 3; inspect data.stdout/data.stderr"
    assert result.data == {
        "argv": [sys.executable, "-c", "import sys; sys.exit(3)"],
        "exit_code": 3,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timeout_seconds": 5,
        "sandbox_mode": "full_access",
        "sandbox_backend": "direct",
        "sandboxed": False,
    }


def test_run_command_returns_oserror_details(tmp_path: Path) -> None:
    argv = ["definitely-missing-project-agent-command"]

    result = RunCommandTool(timeout_seconds=5, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": argv},
    )

    assert result.is_error is True
    assert result.error_code == "command_execution_failed"
    assert result.content == "failed to run command; inspect data.message"
    assert result.data is not None
    assert result.data["argv"] == argv
    assert result.data["exception_type"] == "FileNotFoundError"
    assert isinstance(result.data["message"], str)
    assert result.data["sandbox_mode"] == "full_access"
    assert result.data["sandbox_backend"] == "direct"
    assert result.data["sandboxed"] is False


def test_run_command_rejects_empty_argv(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=5, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": []},
    )

    assert result.is_error is True
    assert result.error_code == "invalid_arguments"
    assert result.data == {"argv": []}


def test_run_command_returns_sandbox_failure(tmp_path: Path) -> None:
    result = RunCommandTool(
        timeout_seconds=5,
        max_output_chars=1000,
        sandbox_runner=_FailingSandboxRunner(),
    ).run(
        workspace_root=tmp_path,
        arguments={"argv": [sys.executable, "-V"]},
    )

    assert result.is_error is True
    assert result.error_code == "sandbox_failed"
    assert result.content == "sandbox failed; inspect data.message"
    assert result.data == {
        "argv": [sys.executable, "-V"],
        "exception_type": "SandboxUnavailableError",
        "message": "job creation failed",
        "sandbox_mode": "workspace_write",
        "sandbox_backend": "fake",
        "sandboxed": False,
    }


class _FailingSandboxRunner:
    @property
    def mode(self) -> SandboxMode:
        return SandboxMode.WORKSPACE_WRITE

    @property
    def backend_name(self) -> str:
        return "fake"

    @property
    def sandboxed(self) -> bool:
        return False

    def run(self, *, argv, cwd, timeout_seconds, env=None):  # type: ignore[no-untyped-def]
        del cwd, timeout_seconds, env
        return SandboxExecutionResult(
            argv=tuple(argv),
            exit_code=None,
            stdout="",
            stderr="",
            timed_out=False,
            sandbox_mode=SandboxMode.WORKSPACE_WRITE,
            sandbox_backend="fake",
            sandboxed=False,
            error_code="sandbox_failed",
            error_message="job creation failed",
            error_type="SandboxUnavailableError",
        )
