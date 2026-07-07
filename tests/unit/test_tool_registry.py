from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.core.types import ToolCall, ToolResult
from project_agent.runtime.permissions import ToolPermissionCategory
from project_agent.runtime.tool_registry import ToolRegistry


class EchoTool:
    name = "echo"
    description = "Echo back content"
    input_schema = {"type": "object"}
    is_read_only = True
    permission_category = ToolPermissionCategory.READ

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"echo: {arguments.get('content', '')}",
            data={"workspace_root": str(workspace_root)},
        )


class DuplicateEchoTool(EchoTool):
    pass


class FlakyReadTool:
    name = "read_file"
    description = "Read file after transient failure"
    input_schema = {"type": "object"}
    is_read_only = True
    permission_category = ToolPermissionCategory.READ

    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            raise OSError("temporary failure")
        return ToolResult(name=self.name, content="ok", data={"calls": self.calls})


class MutatingTool:
    name = "write_file"
    description = "Never retry mutating tool"
    input_schema = {"type": "object"}
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        self.calls += 1
        raise OSError("disk full")


class ExplodingTool:
    name = "explode"
    description = "Raise a runtime error"
    input_schema = {"type": "object"}
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        raise RuntimeError("boom")


def test_tool_registry_rejects_duplicate_tool_names() -> None:
    with pytest.raises(ValueError, match="duplicate tool name: echo"):
        ToolRegistry([EchoTool(), DuplicateEchoTool()])


def test_tool_registry_returns_unknown_tool_error(tmp_path: Path) -> None:
    registry = ToolRegistry([EchoTool()])

    result = registry.invoke(
        tool_call=ToolCall(name="missing", arguments={}),
        workspace_root=tmp_path,
    )

    assert result.is_error is True
    assert result.error_code == "tool_not_found"
    assert result.content == "tool not found: missing"
    assert result.data == {
        "requested_tool": "missing",
        "available_tools": ("echo",),
    }


def test_tool_registry_retries_read_only_tools_once_on_oserror(tmp_path: Path) -> None:
    tool = FlakyReadTool()
    registry = ToolRegistry([tool])

    result = registry.invoke(
        tool_call=ToolCall(name="read_file", arguments={}),
        workspace_root=tmp_path,
    )

    assert result.is_error is False
    assert result.content == "ok"
    assert tool.calls == 2


def test_tool_registry_does_not_retry_mutating_tools(tmp_path: Path) -> None:
    tool = MutatingTool()
    registry = ToolRegistry([tool])

    result = registry.invoke(
        tool_call=ToolCall(name="write_file", arguments={"path": "a.txt"}),
        workspace_root=tmp_path,
    )

    assert result.is_error is True
    assert result.error_code == "tool_execution_failed"
    assert result.content == "tool execution failed; inspect data.message"
    assert result.retryable is False
    assert result.data == {
        "tool_name": "write_file",
        "arguments": {"path": "a.txt"},
        "exception_type": "OSError",
        "message": "disk full",
    }
    assert tool.calls == 1


def test_tool_registry_returns_generic_exception_details(tmp_path: Path) -> None:
    registry = ToolRegistry([ExplodingTool()])

    result = registry.invoke(
        tool_call=ToolCall(name="explode", arguments={"value": 1}),
        workspace_root=tmp_path,
    )

    assert result.is_error is True
    assert result.error_code == "tool_execution_failed"
    assert result.content == "tool execution failed; inspect data.message"
    assert result.data == {
        "tool_name": "explode",
        "arguments": {"value": 1},
        "exception_type": "RuntimeError",
        "message": "boom",
    }
