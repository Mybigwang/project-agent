from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.core.types import Message, SessionState, Task, TaskPlan, ToolCall
from project_agent.errors import SessionError
from project_agent.runtime.session_store import FileSessionStore


def test_file_session_store_returns_empty_state_for_new_session(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)

    assert store.load("session-1") == SessionState(messages=(), task_plan=None)


def test_file_session_store_persists_session_state(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    state = SessionState(
        messages=(
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ),
        task_plan=TaskPlan(
            tasks=(
                Task(
                    id="task_1",
                    title="Inspect request",
                    description="Understand the user request",
                    status="completed",
                ),
                Task(
                    id="task_2",
                    title="Implement change",
                    description="Make the requested change",
                    status="blocked",
                    dependencies=("task_1",),
                    attempts=1,
                    last_error="waiting for dependency",
                ),
            )
        ),
    )

    store.save("session-1", state)

    assert store.load("session-1") == state


def test_file_session_store_rejects_path_traversal_session_id(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)

    with pytest.raises(SessionError, match="invalid session id"):
        store.save("../escape", SessionState(messages=(Message(role="user", content="hello"),)))


def test_file_session_store_persists_tool_call_messages(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)
    state = SessionState(
        messages=(
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),
                ),
            ),
            Message(role="tool", content="echo: ping", tool_call_id="call_123"),
        )
    )

    store.save("session-1", state)

    assert store.load("session-1") == state


@pytest.mark.parametrize(
    "payload",
    [
        '{"messages": [{"role": "invalid", "content": "hello"}], "task_plan": null}',
        '{"messages": [{"role": "user", "content": 123}], "task_plan": null}',
        (
            '{"messages": [{"role": "tool", "content": "ok", '
            '"tool_call_id": 123}], "task_plan": null}'
        ),
        (
            '{"messages": [{"role": "assistant", "content": "", '
            '"tool_calls": [{}]}], "task_plan": null}'
        ),
        (
            '{"messages": [{"role": "assistant", "content": "", '
            '"tool_calls": [{"name": "echo", "arguments": []}]}], '
            '"task_plan": null}'
        ),
        (
            '{"messages": [{"role": "assistant", "content": "", '
            '"tool_calls": [{"name": "echo", "arguments": {}}]}], '
            '"task_plan": null}'
        ),
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


@pytest.mark.parametrize(
    "task_plan",
    [
        (
            '{"tasks": [{"id": "", "title": "A", "description": "A", '
            '"status": "pending", "dependencies": [], "attempts": 0, '
            '"last_error": null}]}'
        ),
        (
            '{"tasks": [{"id": "task_1", "title": "", "description": "A", '
            '"status": "pending", "dependencies": [], "attempts": 0, '
            '"last_error": null}]}'
        ),
        (
            '{"tasks": [{"id": "task_1", "title": "A", "description": "A", '
            '"status": "pending", "dependencies": [], "attempts": 0, '
            '"last_error": null}, {"id": "task_1", "title": "B", '
            '"description": "B", "status": "pending", "dependencies": [], '
            '"attempts": 0, "last_error": null}]}'
        ),
        (
            '{"tasks": [{"id": "task_1", "title": "A", "description": "A", '
            '"status": "pending", "dependencies": ["missing"], '
            '"attempts": 0, "last_error": null}]}'
        ),
        (
            '{"tasks": [{"id": "task_1", "title": "A", "description": "A", '
            '"status": "pending", "dependencies": ["task_2"], '
            '"attempts": 0, "last_error": null}, '
            '{"id": "task_2", "title": "B", "description": "B", '
            '"status": "pending", "dependencies": ["task_1"], '
            '"attempts": 0, "last_error": null}]}'
        ),
    ],
)
def test_file_session_store_rejects_invalid_task_plan_schema(
    tmp_path: Path,
    task_plan: str,
) -> None:
    store = FileSessionStore(tmp_path)
    path = tmp_path / "session-1.json"
    path.write_text(f'{{"messages": [], "task_plan": {task_plan}}}', encoding="utf-8")

    with pytest.raises(SessionError, match="failed to load session: session-1"):
        store.load("session-1")
