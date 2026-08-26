from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from project_agent.runtime.context.git import GitContextCollector
from project_agent.runtime.sandbox import SandboxExecutionResult, SandboxMode


def test_git_context_collector_collects_branch_status_diff_and_commits(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...]) -> SandboxExecutionResult:
        calls.append(argv)
        command = tuple(argv[1:])
        if command == ("rev-parse", "--abbrev-ref", "HEAD"):
            return _sandbox_result(argv=argv, stdout="main\n")
        if command == ("status", "--short", "--branch"):
            return _sandbox_result(argv=argv, stdout="## main\n M src/app.py\n")
        if command == ("diff", "--no-ext-diff", "--", "."):
            return _sandbox_result(
                argv=argv,
                stdout="diff --git a/src/app.py b/src/app.py\n+change\n",
            )
        if command == ("log", "--oneline", "-n", "2"):
            return _sandbox_result(argv=argv, stdout="abc123 add context\ndef456 init\n")
        raise AssertionError(argv)

    context = GitContextCollector(
        timeout_seconds=1.0,
        max_diff_chars=11,
        recent_commits_count=2,
        sandbox_runner=_FakeSandboxRunner(fake_run),
    ).collect(tmp_path)

    assert context.is_available is True
    assert context.branch == "main"
    assert "M src/app.py" in context.status
    assert context.diff == "diff --git "
    assert context.recent_commits == ("abc123 add context", "def456 init")
    assert calls[0] == ("git", "rev-parse", "--abbrev-ref", "HEAD")


def test_git_context_collector_returns_unavailable_when_git_fails(
    tmp_path: Path,
) -> None:
    def fake_run(argv: tuple[str, ...]) -> SandboxExecutionResult:
        if argv[1:4] == ("rev-parse", "--abbrev-ref", "HEAD"):
            return _sandbox_result(
                argv=argv,
                stderr="fatal: not a git repository",
                exit_code=128,
            )
        raise AssertionError("should stop after branch failure")

    context = GitContextCollector(
        timeout_seconds=1.0,
        max_diff_chars=100,
        recent_commits_count=3,
        sandbox_runner=_FakeSandboxRunner(fake_run),
    ).collect(tmp_path)

    assert context.is_available is False
    assert context.branch is None
    assert context.status == ""
    assert context.diff == ""
    assert context.recent_commits == ()
    assert "not a git repository" in (context.error or "")


def test_git_context_collector_returns_unavailable_on_timeout(
    tmp_path: Path,
) -> None:
    def fake_run(argv: tuple[str, ...]) -> SandboxExecutionResult:
        return _sandbox_result(argv=argv, timed_out=True, error_code="command_timeout")

    context = GitContextCollector(
        timeout_seconds=1.0,
        max_diff_chars=100,
        recent_commits_count=3,
        sandbox_runner=_FakeSandboxRunner(fake_run),
    ).collect(tmp_path)

    assert context.is_available is False
    assert context.error == "git command timed out"


class _FakeSandboxRunner:
    def __init__(
        self,
        run_result_builder: Callable[[tuple[str, ...]], SandboxExecutionResult],
    ) -> None:
        self._run_result_builder = run_result_builder

    @property
    def mode(self) -> SandboxMode:
        return SandboxMode.READ_ONLY

    @property
    def backend_name(self) -> str:
        return "fake"

    @property
    def sandboxed(self) -> bool:
        return True

    def run(
        self,
        *,
        argv: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> SandboxExecutionResult:
        del cwd, timeout_seconds, env
        return self._run_result_builder(tuple(argv))


def _sandbox_result(
    *,
    argv: tuple[str, ...],
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    error_code: str | None = None,
) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        argv=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        sandbox_mode=SandboxMode.READ_ONLY,
        sandbox_backend="fake",
        sandboxed=True,
        error_code=error_code,
    )
