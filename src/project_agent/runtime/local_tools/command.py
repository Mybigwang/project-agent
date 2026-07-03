from __future__ import annotations

import subprocess
from pathlib import Path

from project_agent.core.types import ToolResult
from project_agent.runtime.permissions.types import ToolPermissionCategory


class RunCommandTool:
    name = "run_command"
    description = "Run a command in the workspace"
    input_schema = {
        "type": "object",
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["argv"],
    }
    is_read_only = False
    permission_category = ToolPermissionCategory.EXECUTE

    def __init__(self, *, timeout_seconds: float, max_output_chars: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        argv = arguments.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) for item in argv)
        ):
            return ToolResult(
                name=self.name,
                content="invalid argv",
                is_error=True,
                error_code="invalid_arguments",
                data={"argv": argv},
            )

        try:
            completed = subprocess.run(
                argv,
                cwd=workspace_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                name=self.name,
                content=(
                    "command timed out; inspect data.argv and data.timeout_seconds"
                ),
                is_error=True,
                error_code="command_timeout",
                data={
                    "argv": argv,
                    "timeout_seconds": self._timeout_seconds,
                },
            )
        except OSError as error:
            return ToolResult(
                name=self.name,
                content="failed to run command; inspect data.message",
                is_error=True,
                error_code="command_execution_failed",
                data={
                    "argv": argv,
                    "exception_type": type(error).__name__,
                    "message": str(error),
                },
            )

        stdout_truncated = len(completed.stdout) > self._max_output_chars
        stderr_truncated = len(completed.stderr) > self._max_output_chars
        stdout = completed.stdout[: self._max_output_chars].rstrip("\n")
        stderr = completed.stderr[: self._max_output_chars].rstrip("\n")
        is_error = completed.returncode != 0
        content = (
            f"command failed with exit code {completed.returncode}; "
            "inspect data.stdout/data.stderr"
            if is_error
            else f"command exited with code {completed.returncode}"
        )
        return ToolResult(
            name=self.name,
            content=content,
            is_error=is_error,
            data={
                "argv": argv,
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "timeout_seconds": self._timeout_seconds,
            },
            error_code="command_failed" if is_error else None,
        )
