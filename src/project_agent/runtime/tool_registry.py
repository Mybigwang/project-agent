from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from project_agent.core.interfaces import Tool
from project_agent.core.types import ToolCall, ToolResult


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        tools_by_name: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in tools_by_name:
                raise ValueError(f"duplicate tool name: {tool.name}")
            tools_by_name = {**tools_by_name, tool.name: tool}
        self._tools_by_name = tools_by_name
        self._tools = tuple(tools)

    @property
    def tools(self) -> tuple[Tool, ...]:
        return self._tools

    def get_tool(self, name: str) -> Tool | None:
        return self._tools_by_name.get(name)

    def invoke(self, *, tool_call: ToolCall, workspace_root: Path) -> ToolResult:
        tool = self._tools_by_name.get(tool_call.name)
        if tool is None:
            return ToolResult(
                name=tool_call.name,
                content=f"tool not found: {tool_call.name}",
                is_error=True,
                error_code="tool_not_found",
            )

        attempts = 2 if tool.is_read_only else 1
        for attempt in range(1, attempts + 1):
            try:
                return tool.run(workspace_root=workspace_root, arguments=tool_call.arguments)
            except OSError as error:
                is_last_attempt = attempt == attempts
                if is_last_attempt:
                    return ToolResult(
                        name=tool.name,
                        content=f"tool execution failed: {error}",
                        is_error=True,
                        error_code="tool_execution_failed",
                        retryable=tool.is_read_only,
                    )
            except Exception as error:
                return ToolResult(
                    name=tool.name,
                    content=f"tool execution failed: {error}",
                    is_error=True,
                    error_code="tool_execution_failed",
                )

        return ToolResult(
            name=tool.name,
            content="tool execution failed",
            is_error=True,
            error_code="tool_execution_failed",
        )
