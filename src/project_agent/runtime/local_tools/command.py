from __future__ import annotations

from pathlib import Path

from project_agent.core.types import ToolResult
from project_agent.runtime.permissions.types import ToolPermissionCategory
from project_agent.runtime.sandbox import DirectSandboxRunner, SandboxMode, SandboxRunner


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

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_output_chars: int,
        sandbox_runner: SandboxRunner | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars
        self._sandbox_runner = sandbox_runner or DirectSandboxRunner(mode=SandboxMode.FULL_ACCESS)

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

        completed = self._sandbox_runner.run(
            argv=argv,
            cwd=workspace_root,
            timeout_seconds=self._timeout_seconds,
        )
        if completed.timed_out:
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
                    "sandbox_mode": completed.sandbox_mode.value,
                    "sandbox_backend": completed.sandbox_backend,
                    "sandboxed": completed.sandboxed,
                },
            )
        if completed.error_code == "sandbox_failed":
            return ToolResult(
                name=self.name,
                content="sandbox failed; inspect data.message",
                is_error=True,
                error_code="sandbox_failed",
                data={
                    "argv": argv,
                    "exception_type": completed.error_type or "SandboxUnavailableError",
                    "message": completed.error_message or "",
                    "sandbox_mode": completed.sandbox_mode.value,
                    "sandbox_backend": completed.sandbox_backend,
                    "sandboxed": completed.sandboxed,
                },
            )
        if completed.error_code == "command_execution_failed":
            return ToolResult(
                name=self.name,
                content="failed to run command; inspect data.message",
                is_error=True,
                error_code="command_execution_failed",
                data={
                    "argv": argv,
                    "exception_type": completed.error_type or "OSError",
                    "message": completed.error_message or "",
                    "sandbox_mode": completed.sandbox_mode.value,
                    "sandbox_backend": completed.sandbox_backend,
                    "sandboxed": completed.sandboxed,
                },
            )

        stdout_truncated = len(completed.stdout) > self._max_output_chars
        stderr_truncated = len(completed.stderr) > self._max_output_chars
        stdout = completed.stdout[: self._max_output_chars].rstrip("\n")
        stderr = completed.stderr[: self._max_output_chars].rstrip("\n")
        exit_code = completed.exit_code if completed.exit_code is not None else 1
        is_error = exit_code != 0
        content = (
            f"command failed with exit code {exit_code}; "
            "inspect data.stdout/data.stderr"
            if is_error
            else f"command exited with code {exit_code}"
        )
        return ToolResult(
            name=self.name,
            content=content,
            is_error=is_error,
            data={
                "argv": argv,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "timeout_seconds": self._timeout_seconds,
                "sandbox_mode": completed.sandbox_mode.value,
                "sandbox_backend": completed.sandbox_backend,
                "sandboxed": completed.sandboxed,
            },
            error_code="command_failed" if is_error else None,
        )
