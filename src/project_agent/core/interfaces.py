from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from project_agent.core.types import (
    Message,
    RepositoryContext,
    SessionState,
    SkillCall,
    TaskPlan,
    ToolCall,
    ToolResult,
)


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
        stream_callback: Callable[[str], None] | None = None,
    ) -> Message | SkillCall | tuple[ToolCall, ...]: ...


@runtime_checkable
class StreamingModelClient(Protocol):
    def stream_complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Iterable[str]: ...


class SessionStore(Protocol):
    def load(self, session_id: str) -> SessionState: ...

    def save(self, session_id: str, state: SessionState) -> None: ...


class Planner(Protocol):
    def create_plan(self, *, user_input: str, history: Sequence[Message]) -> TaskPlan: ...

    def replan_after_failure(
        self,
        *,
        user_input: str,
        history: Sequence[Message],
        task_plan: TaskPlan,
        failed_task_id: str,
        error: str,
    ) -> TaskPlan: ...


class RepositoryContextBuilderProtocol(Protocol):
    def build(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        history: Sequence[Message],
    ) -> RepositoryContext: ...
