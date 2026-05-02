from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from project_agent.core.types import Message, ToolCall
from project_agent.errors import SessionError

SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


class InMemorySessionStore:
    def __init__(self) -> None:
        self._messages: dict[str, tuple[Message, ...]] = {}

    def load(self, session_id: str) -> tuple[Message, ...]:
        return self._messages.get(session_id, ())

    def save(self, session_id: str, messages: Sequence[Message]) -> None:
        self._messages = {**self._messages, session_id: tuple(messages)}


class FileSessionStore:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def load(self, session_id: str) -> tuple[Message, ...]:
        path = self._path_for(session_id)
        if not path.exists():
            return ()

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return tuple(_deserialize_message(item) for item in payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise SessionError(f"failed to load session: {session_id}") from error

    def save(self, session_id: str, messages: Sequence[Message]) -> None:
        path = self._path_for(session_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                [asdict(message) for message in messages], ensure_ascii=False, indent=2
            )
            path.write_text(payload, encoding="utf-8")
        except OSError as error:
            raise SessionError(f"failed to save session: {session_id}") from error

    def _path_for(self, session_id: str) -> Path:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionError(f"invalid session id: {session_id}")

        root_dir = self._root_dir.resolve()
        path = (root_dir / f"{session_id}.json").resolve()
        try:
            path.relative_to(root_dir)
        except ValueError as error:
            raise SessionError(f"invalid session id: {session_id}") from error
        return path


def _deserialize_message(item: object) -> Message:
    if not isinstance(item, dict):
        raise ValueError("session message must be an object")
    role = item["role"]
    content = item["content"]
    tool_call_id = item.get("tool_call_id")
    if role not in MESSAGE_ROLES:
        raise ValueError("session message role is invalid")
    if not isinstance(content, str):
        raise ValueError("session message content must be a string")
    if tool_call_id is not None and not isinstance(tool_call_id, str):
        raise ValueError("session message tool call id must be a string")
    return Message(
        role=role,
        content=content,
        tool_calls=tuple(_deserialize_tool_call(tool_call) for tool_call in item.get("tool_calls", ())),
        tool_call_id=tool_call_id,
    )


def _deserialize_tool_call(item: object) -> ToolCall:
    if not isinstance(item, dict):
        raise ValueError("session tool call must be an object")
    name = item["name"]
    arguments = item.get("arguments", {})
    call_id = item.get("call_id")
    if not isinstance(name, str):
        raise ValueError("session tool call name must be a string")
    if not isinstance(arguments, dict):
        raise ValueError("session tool call arguments must be an object")
    if not isinstance(call_id, str) or not call_id:
        raise ValueError("session tool call id must be a non-empty string")
    return ToolCall(name=name, arguments=arguments, call_id=call_id)
