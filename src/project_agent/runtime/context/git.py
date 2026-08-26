from __future__ import annotations

from pathlib import Path

from project_agent.core.types import GitContext
from project_agent.runtime.sandbox import DirectSandboxRunner, SandboxMode, SandboxRunner


class GitContextCollector:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_diff_chars: int,
        recent_commits_count: int,
        sandbox_runner: SandboxRunner | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_diff_chars = max_diff_chars
        self._recent_commits_count = recent_commits_count
        self._sandbox_runner = sandbox_runner or DirectSandboxRunner(mode=SandboxMode.FULL_ACCESS)

    def collect(self, workspace_root: Path) -> GitContext:
        branch_result = self._run_git(workspace_root, ("rev-parse", "--abbrev-ref", "HEAD"))
        if branch_result.is_error:
            return GitContext(
                is_available=False,
                branch=None,
                status="",
                diff="",
                recent_commits=(),
                error=branch_result.error,
            )

        status_result = self._run_git(workspace_root, ("status", "--short", "--branch"))
        diff_result = self._run_git(workspace_root, ("diff", "--no-ext-diff", "--", "."))
        log_result = self._run_git(
            workspace_root, ("log", "--oneline", "-n", str(self._recent_commits_count))
        )

        return GitContext(
            is_available=True,
            branch=branch_result.output.strip(),
            status="" if status_result.is_error else status_result.output.strip(),
            diff="" if diff_result.is_error else diff_result.output[: self._max_diff_chars],
            recent_commits=()
            if log_result.is_error
            else tuple(line for line in log_result.output.splitlines() if line),
            error=None,
        )

    def _run_git(self, workspace_root: Path, arguments: tuple[str, ...]) -> _GitCommandResult:
        argv = ["git", *arguments]
        completed = self._sandbox_runner.run(
            argv=argv,
            cwd=workspace_root,
            timeout_seconds=self._timeout_seconds,
        )
        if completed.timed_out:
            return _GitCommandResult(output="", error="git command timed out")
        if completed.error_code is not None:
            return _GitCommandResult(
                output="",
                error=f"git command failed: {completed.error_message or completed.error_code}",
            )

        if completed.exit_code != 0:
            error_message = (
                completed.stderr.strip() or completed.stdout.strip() or "git command failed"
            )
            return _GitCommandResult(output="", error=error_message)
        return _GitCommandResult(output=completed.stdout, error=None)


class _GitCommandResult:
    def __init__(self, *, output: str, error: str | None) -> None:
        self.output = output
        self.error = error

    @property
    def is_error(self) -> bool:
        return self.error is not None
