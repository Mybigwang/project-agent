from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "completed", "blocked"]


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass(frozen=True)
class SkillCall:
    name: str
    raw_args: str = ""
    call_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    name: str
    content: str
    is_error: bool = False
    data: dict[str, Any] | None = None
    error_code: str | None = None
    retryable: bool = False

    def to_message_content(self) -> str:
        payload = {
            "name": self.name,
            "status": "error" if self.is_error else "ok",
            "content": self.content,
            "data": self.data,
            "error_code": self.error_code,
            "retryable": self.retryable,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    description: str
    status: TaskStatus = "pending"
    dependencies: tuple[str, ...] = ()
    attempts: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class TaskPlan:
    tasks: tuple[Task, ...]


@dataclass(frozen=True)
class SessionState:
    messages: tuple[Message, ...] = ()
    task_plan: TaskPlan | None = None


@dataclass(frozen=True)
class WorkspaceContext:
    root: Path
    top_level_entries: tuple[str, ...]
    key_paths: tuple[str, ...]


@dataclass(frozen=True)
class GitContext:
    is_available: bool
    branch: str | None
    status: str
    diff: str
    recent_commits: tuple[str, ...]
    error: str | None


@dataclass(frozen=True)
class RuleDocument:
    path: str
    content: str
    truncated: bool


@dataclass(frozen=True)
class RelevantFileExcerpt:
    path: str
    reason: str
    excerpt: str
    truncated: bool


@dataclass(frozen=True)
class RepositoryContext:
    rendered: str
    workspace: WorkspaceContext | None
    git: GitContext | None
    rules: tuple[RuleDocument, ...]
    relevant_files: tuple[RelevantFileExcerpt, ...]


@dataclass(frozen=True)
class AgentTraceStep:
    step: int
    event: str
    summary: str
    tool_name: str | None = None
    is_error: bool = False
    task_id: str | None = None
    task_status: TaskStatus | None = None
    permission_decision: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class RunResult:
    final_message: Message
    messages: tuple[Message, ...]
    trace: tuple[AgentTraceStep, ...]
    task_plan: TaskPlan | None = None
