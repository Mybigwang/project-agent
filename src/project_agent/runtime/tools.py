from __future__ import annotations

from pathlib import Path

from project_agent.core.interfaces import Tool
from project_agent.core.types import ToolResult
from project_agent.runtime.permissions.types import ToolPermissionCategory
from project_agent.runtime.local_tools import RunCommandTool
from project_agent.runtime.local_tools.filesystem import (
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    WriteFileTool,
)
from project_agent.runtime.local_tools.search import SearchCodeTool


class EchoTool:
    name = "echo"
    description = "Echo back content"
    input_schema = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
    }
    is_read_only = True
    permission_category = ToolPermissionCategory.READ

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(name=self.name, content=f"echo: {arguments.get('content', '')}")


def build_default_tools(
    *, max_file_read_chars: int, command_timeout_seconds: float, max_command_output_chars: int
) -> list[Tool]:
    return [
        ReadFileTool(max_chars=max_file_read_chars),
        WriteFileTool(),
        EditFileTool(),
        ListFilesTool(),
        SearchCodeTool(),
        RunCommandTool(
            timeout_seconds=command_timeout_seconds, max_output_chars=max_command_output_chars
        ),
    ]
