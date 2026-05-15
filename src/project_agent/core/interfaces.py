from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from project_agent.core.types import (
    BudgetSnapshot,
    CompactionSummarySnapshot,
    ContextManagementState,
    MemoryContext,
    Message,
    RepositoryContext,
    SessionState,
    SkillCall,
    TaskPlan,
    ToolCall,
    ToolResult,
)
from project_agent.runtime.permissions.types import ToolPermissionCategory


class Plugin(Protocol):
    name: str

    def setup(self) -> None: ...


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    is_read_only: bool
    permission_category: ToolPermissionCategory

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


class MemoryContextBuilderProtocol(Protocol):
    def build(self, *, user_input: str) -> MemoryContext: ...


class ContextBudgetEstimatorProtocol(Protocol):
    def estimate_messages(
        self,
        *,
        messages: Sequence[Message],
        token_limit: int,
        profile: str,
        version: str,
    ) -> BudgetSnapshot: ...


class CompactionSummaryBuilderProtocol(Protocol):
    def build_summary(
        self,
        *,
        messages: Sequence[Message],
        task_plan: TaskPlan | None,
        existing_state: ContextManagementState | None,
    ) -> CompactionSummarySnapshot: ...


class ContextManagerProtocol(Protocol):
    def prepare_messages(
        self,
        *,
        messages: Sequence[Message],
        task_plan: TaskPlan | None,
        existing_state: ContextManagementState | None,
    ) -> tuple[tuple[Message, ...], ContextManagementState | None]: ...
