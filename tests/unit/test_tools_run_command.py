from __future__ import annotations

import sys
from pathlib import Path

from project_agent.runtime.local_tools.command import RunCommandTool


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
    }


def test_run_command_returns_timeout_error(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=0.01, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": [sys.executable, "-c", "import time; time.sleep(0.2)"]},
    )

    assert result.is_error is True
    assert result.error_code == "command_timeout"


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
    }


def test_run_command_marks_non_zero_exit_as_error(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=5, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": [sys.executable, "-c", "import sys; sys.exit(3)"]},
    )

    assert result.is_error is True
    assert result.error_code == "command_failed"
    assert result.data == {
        "argv": [sys.executable, "-c", "import sys; sys.exit(3)"],
        "exit_code": 3,
        "stdout": "",
        "stderr": "",
    }


def test_run_command_rejects_empty_argv(tmp_path: Path) -> None:
    result = RunCommandTool(timeout_seconds=5, max_output_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"argv": []},
    )

    assert result.is_error is True
    assert result.error_code == "invalid_arguments"
