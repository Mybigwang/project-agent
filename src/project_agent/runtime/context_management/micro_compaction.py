from __future__ import annotations

import json
from collections.abc import Sequence

from project_agent.core.types import Message


class MicroCompactor:
    def __init__(self, *, recent_tool_results_keep: int, tool_result_preview_chars: int) -> None:
        self.recent_tool_results_keep = recent_tool_results_keep
        self.tool_result_preview_chars = tool_result_preview_chars

    def compact_messages(self, messages: Sequence[Message]) -> tuple[Message, ...]:
        tool_indexes = tuple(index for index, message in enumerate(messages) if message.role == "tool")
        keep_indexes = frozenset(tool_indexes[-self.recent_tool_results_keep :])
        compacted: list[Message] = []
        for index, message in enumerate(messages):
            if message.role != "tool" or index in keep_indexes:
                compacted.append(message)
                continue
            compacted.append(
                Message(
                    role=message.role,
                    content=self._compact_tool_content(message.content),
                    tool_calls=message.tool_calls,
                    tool_call_id=message.tool_call_id,
                )
            )
        return tuple(compacted)

    def _compact_tool_content(self, content: str) -> str:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            preview = content[: self.tool_result_preview_chars]
            return json.dumps(
                {
                    "status": "elided",
                    "content": preview,
                    "truncated": len(content) > self.tool_result_preview_chars,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        if not isinstance(payload, dict):
            return content
        preview = str(payload.get("content", ""))[: self.tool_result_preview_chars]
        compacted_payload = {
            "name": payload.get("name"),
            "status": payload.get("status", "ok"),
            "content": preview,
            "data": payload.get("data"),
            "error_code": payload.get("error_code"),
            "retryable": payload.get("retryable", False),
            "elided": True,
        }
        return json.dumps(compacted_payload, ensure_ascii=False, sort_keys=True)
