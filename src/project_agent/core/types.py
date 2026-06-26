from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "completed", "blocked"]
AgentKind = Literal["subagent", "worker", "coordinator"]
AgentRole = Literal["explore", "plan", "worker", "verification", "coordinator", "generalPurpose"]
AgentRunStatus = Literal["created", "running", "completed", "failed", "cancelled"]
AgentVerdict = Literal["PASS", "FAIL", "PARTIAL"]


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
class BudgetSnapshot:
    estimated_tokens_used: int
    estimated_tokens_limit: int
    fill_ratio: float
    profile: str
    version: str


@dataclass(frozen=True)
class AutoCompactionState:
    fail_streak: int = 0
    last_fill_ratio: float | None = None
    circuit_open: bool = False
    last_error: str | None = None
    last_compacted_turn: int | None = None


@dataclass(frozen=True)
class CompactionSummarySnapshot:
    profile: str
    version: str
    summary_text: str
    intent: str
    concepts: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    message_highlights: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    current_focus: str | None = None
    environment: tuple[str, ...] = ()
    kept_conclusions: tuple[str, ...] = ()
    source_message_count: int = 0


@dataclass(frozen=True)
class ContextManagementState:
    profile: str
    version: str
    turn_count: int = 0
    latest_budget: BudgetSnapshot | None = None
    auto_compaction: AutoCompactionState = field(default_factory=AutoCompactionState)
    summary_snapshot: CompactionSummarySnapshot | None = None


@dataclass(frozen=True)
class AgentStructuredResult:
    summary: str
    evidence: tuple[str, ...] = ()
    touched_files: tuple[str, ...] = ()
    commands_run: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    verdict: AgentVerdict | None = None


@dataclass(frozen=True)
class AgentSpec:
    name: str | None
    description: str
    prompt: str
    kind: AgentKind = "subagent"
    role: AgentRole = "generalPurpose"
    subagent_type: str | None = None
    model: str | None = None
    run_in_background: bool = False
    parent_session_id: str | None = None
    target_files: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    depth: int = 0


@dataclass(frozen=True)
class AgentRunRecord:
    agent_id: str
    session_id: str
    name: str
    description: str
    kind: AgentKind
    status: AgentRunStatus
    role: AgentRole = "generalPurpose"
    readonly: bool = False
    result_summary: str | None = None
    error: str | None = None
    structured_result: AgentStructuredResult | None = None
    verdict: AgentVerdict | None = None
    parent_session_id: str | None = None
    depth: int = 1


@dataclass(frozen=True)
class AgentNotification:
    agent_id: str
    status: AgentRunStatus
    summary: str
    result: str
    role: AgentRole = "generalPurpose"
    verdict: AgentVerdict | None = None
    structured_result: AgentStructuredResult | None = None
    usage: str | None = None


@dataclass(frozen=True)
class MultiAgentTraceStep:
    step: int
    event: str
    summary: str = ""
    agent_id: str | None = None
    agent_name: str | None = None
    status: AgentRunStatus | None = None
    is_error: bool = False


@dataclass(frozen=True)
class SessionState:
    messages: tuple[Message, ...] = ()
    task_plan: TaskPlan | None = None
    context_state: ContextManagementState | None = None
    agent_runs: tuple[AgentRunRecord, ...] = ()


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
class MemoryFile:
    path: Path
    relative_path: str
    title: str
    description: str
    mtime: float


@dataclass(frozen=True)
class MemoryContext:
    prompt: str
    relevant_files: tuple[MemoryFile, ...]


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
    memory_context: MemoryContext | None = None


@dataclass(frozen=True)
class MultiAgentRunResult:
    final_message: Message
    messages: tuple[Message, ...]
    trace: tuple[AgentTraceStep | MultiAgentTraceStep, ...]
    task_plan: TaskPlan | None = None
    agents: tuple[AgentRunRecord, ...] = ()
