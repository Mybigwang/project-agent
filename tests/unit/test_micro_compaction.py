from __future__ import annotations

import json

from project_agent.core.types import Message
from project_agent.runtime.context_management.micro_compaction import MicroCompactor


def test_micro_compactor_keeps_recent_tool_results_and_elides_older_ones() -> None:
    compactor = MicroCompactor(recent_tool_results_keep=2, tool_result_preview_chars=4)
    messages = (
        Message(role="tool", content=json.dumps({"name": "a", "status": "ok", "content": "first"}), tool_call_id="1"),
        Message(role="tool", content=json.dumps({"name": "b", "status": "ok", "content": "second"}), tool_call_id="2"),
        Message(role="tool", content=json.dumps({"name": "c", "status": "ok", "content": "third"}), tool_call_id="3"),
    )

    compacted = compactor.compact_messages(messages)

    first_payload = json.loads(compacted[0].content)
    assert first_payload["elided"] is True
    assert first_payload["content"] == "firs"
    assert compacted[1] == messages[1]
    assert compacted[2] == messages[2]
