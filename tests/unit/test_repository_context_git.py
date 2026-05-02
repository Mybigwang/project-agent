from __future__ import annotations

import subprocess
from pathlib import Path

from project_agent.runtime.context.git import GitContextCollector


class CompletedProcess:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_git_context_collector_collects_branch_status_diff_and_commits(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: list[str], **_: object) -> CompletedProcess:
        calls.append(tuple(argv))
        command = tuple(argv[1:])
        if command == ("rev-parse", "--abbrev-ref", "HEAD"):
            return CompletedProcess(stdout="main\n")
        if command == ("status", "--short", "--branch"):
            return CompletedProcess(stdout="## main\n M src/app.py\n")
        if command == ("diff", "--no-ext-diff", "--", "."):
            return CompletedProcess(stdout="diff --git a/src/app.py b/src/app.py\n+change\n")
        if command == ("log", "--oneline", "-n", "2"):
            return CompletedProcess(stdout="abc123 add context\ndef456 init\n")
        raise AssertionError(argv)

    monkeypatch.setattr(subprocess, "run", fake_run)

    context = GitContextCollector(
        timeout_seconds=1.0,
        max_diff_chars=11,
        recent_commits_count=2,
    ).collect(tmp_path)

    assert context.is_available is True
    assert context.branch == "main"
    assert "M src/app.py" in context.status
    assert context.diff == "diff --git "
    assert context.recent_commits == ("abc123 add context", "def456 init")
    assert calls[0] == ("git", "rev-parse", "--abbrev-ref", "HEAD")


def test_git_context_collector_returns_unavailable_when_git_fails(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    def fake_run(argv: list[str], **_: object) -> CompletedProcess:
        if argv[1:4] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return CompletedProcess(stderr="fatal: not a git repository", returncode=128)
        raise AssertionError("should stop after branch failure")

    monkeypatch.setattr(subprocess, "run", fake_run)

    context = GitContextCollector(
        timeout_seconds=1.0,
        max_diff_chars=100,
        recent_commits_count=3,
    ).collect(tmp_path)

    assert context.is_available is False
    assert context.branch is None
    assert context.status == ""
    assert context.diff == ""
    assert context.recent_commits == ()
    assert "not a git repository" in (context.error or "")


def test_git_context_collector_returns_unavailable_on_timeout(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    def fake_run(argv: list[str], **_: object) -> CompletedProcess:
        raise subprocess.TimeoutExpired(argv, timeout=1.0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    context = GitContextCollector(
        timeout_seconds=1.0,
        max_diff_chars=100,
        recent_commits_count=3,
    ).collect(tmp_path)

    assert context.is_available is False
    assert context.error == "git command timed out"
