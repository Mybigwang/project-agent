from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.core.types import Message, ToolCall
from project_agent.errors import SessionError
from project_agent.runtime.session_store import FileSessionStore


def test_file_session_store_returns_empty_history_for_new_session(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)

    assert store.load("session-1") == ()


def test_file_session_store_persists_messages(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    messages = (
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    )

    store.save("session-1", messages)

    assert store.load("session-1") == messages


def test_file_session_store_rejects_path_traversal_session_id(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)

    with pytest.raises(SessionError, match="invalid session id"):
        store.save("../escape", (Message(role="user", content="hello"),))




def test_file_session_store_persists_tool_call_messages(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    messages = (
        Message(
            role="assistant",
            content="",
            tool_calls=(ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),),
        ),
        Message(role="tool", content="echo: ping", tool_call_id="call_123"),
    )

    store.save("session-1", messages)

    assert store.load("session-1") == messages


@pytest.mark.parametrize(
    "payload",
    [
        '[{"role": "invalid", "content": "hello"}]',
        '[{"role": "user", "content": 123}]',
        '[{"role": "tool", "content": "ok", "tool_call_id": 123}]',
        '[{"role": "assistant", "content": "", "tool_calls": [{}]}]',
        '[{"role": "assistant", "content": "", "tool_calls": [{"name": "echo", "arguments": []}]}]',
        '[{"role": "assistant", "content": "", "tool_calls": [{"name": "echo", "arguments": {}}]}]',
    ],
)
def test_file_session_store_rejects_invalid_message_schema(
    tmp_path: Path,
    payload: str,
) -> None:
    store = FileSessionStore(tmp_path)
    path = tmp_path / "session-1.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(SessionError, match="failed to load session: session-1"):
        store.load("session-1")
