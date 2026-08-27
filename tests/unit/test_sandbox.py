from __future__ import annotations

import os
from pathlib import Path

import pytest

import project_agent.runtime.sandbox as sandbox_module
from project_agent.runtime.sandbox import (
    DirectSandboxRunner,
    SandboxMode,
    WindowsRestrictedSandboxRunner,
    build_sandbox_runner,
)
from project_agent.runtime.windows_process import _wrap_command_if_needed


def test_build_sandbox_runner_uses_direct_for_full_access() -> None:
    runner = build_sandbox_runner(mode=SandboxMode.FULL_ACCESS)

    assert isinstance(runner, DirectSandboxRunner)
    assert runner.backend_name == "direct"


def test_build_sandbox_runner_uses_windows_restricted_for_sandboxed_modes() -> None:
    runner = build_sandbox_runner(mode=SandboxMode.WORKSPACE_WRITE)

    assert isinstance(runner, WindowsRestrictedSandboxRunner)
    assert runner.backend_name == "windows_restricted_token"
    assert runner.sandboxed is True


def test_windows_runner_reports_failure_without_windows_support(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = build_sandbox_runner(mode=SandboxMode.READ_ONLY)
    monkeypatch.setattr(sandbox_module.os, "name", "posix", raising=False)

    result = runner.run(
        argv=["echo", "hello"],
        cwd=tmp_path,
        timeout_seconds=1.0,
    )

    assert result.error_code == "sandbox_failed"
    assert result.sandbox_backend == "windows_restricted_token"
    assert result.sandboxed is False


def test_windows_runner_wraps_cmd_commands(
    tmp_path: Path,
) -> None:
    wrapped = _wrap_command_if_needed(["npx.cmd", "-y", "@modelcontextprotocol/server-github"])

    assert wrapped[0].lower().endswith("cmd.exe")
    assert wrapped[1:4] == ("/d", "/s", "/c")


@pytest.mark.skipif(os.name != "nt", reason="windows-only sandbox behavior")
def test_windows_restricted_runner_executes_command_in_workspace(tmp_path: Path) -> None:
    runner = build_sandbox_runner(mode=SandboxMode.WORKSPACE_WRITE)
    result = runner.run(
        argv=["cmd.exe", "/d", "/s", "/c", "echo ok"],
        cwd=tmp_path,
        timeout_seconds=5.0,
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"
    assert result.stderr == ""
    assert result.sandbox_backend == "windows_restricted_token"
    assert result.sandboxed is True
