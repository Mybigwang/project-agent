from __future__ import annotations

from pathlib import Path
from typing import Any

from project_agent.core.types import ToolResult
from project_agent.errors import AgentError
from project_agent.runtime.memory.maintenance import MemoryMaintenance
from project_agent.runtime.permissions.types import ToolPermissionCategory


class RememberTool:
    name = "remember"
    description = (
        "Save a durable memory when the user explicitly asks to remember it. "
        "Provide the user's evidence, a lowercase topic slug, and concise content. "
        "Pin only when the user asks for permanent retention. Do not save credentials."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "content": {"type": "string"},
            "evidence": {"type": "string"},
            "pinned": {"type": "boolean"},
        },
        "required": ["topic", "content", "evidence"],
        "additionalProperties": False,
    }
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

    def __init__(self, maintenance: MemoryMaintenance, session_id: str) -> None:
        self.maintenance = maintenance
        self.session_id = session_id

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        try:
            self.maintenance.store.memory_dir.relative_to(workspace_root.resolve())
            topic, content, evidence = (
                arguments.get(key) for key in ("topic", "content", "evidence")
            )
            pinned = arguments.get("pinned", False)
            if (
                not isinstance(topic, str)
                or not isinstance(content, str)
                or not isinstance(evidence, str)
            ):
                raise ValueError("topic, content and evidence must be strings")
            if not isinstance(pinned, bool):
                raise ValueError("pinned must be a boolean")
            self.maintenance.remember(
                topic=topic,
                content=content,
                evidence=evidence,
                session_id=self.session_id,
                pinned=pinned,
            )
            return ToolResult(name=self.name, content=f"Saved memory: topics/{topic}.md")
        except (AgentError, OSError, ValueError) as error:
            return ToolResult(
                name=self.name, content=str(error), is_error=True, error_code="memory_write_failed"
            )
