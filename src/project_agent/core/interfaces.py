from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from project_agent.core.types import Message, RepositoryContext, ToolCall, ToolResult


class Plugin(Protocol):
    name: str

    def setup(self) -> None: ...


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    is_read_only: bool

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult: ...


class ModelClient(Protocol):
    name: str

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Message | ToolCall: ...


@runtime_checkable
class StreamingModelClient(Protocol):
    def stream_complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Iterable[str]: ...


class SessionStore(Protocol):
    def load(self, session_id: str) -> Sequence[Message]: ...

    def save(self, session_id: str, messages: Sequence[Message]) -> None: ...


class RepositoryContextBuilderProtocol(Protocol):
    def build(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        history: Sequence[Message],
    ) -> RepositoryContext: ...
