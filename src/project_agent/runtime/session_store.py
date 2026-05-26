from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from project_agent.core.types import (
    AgentRunRecord,
    AutoCompactionState,
    BudgetSnapshot,
    CompactionSummarySnapshot,
    ContextManagementState,
    Message,
    SessionState,
    Task,
    TaskPlan,
    ToolCall,
)
from project_agent.errors import SessionError

SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
TASK_STATUSES = frozenset({"pending", "in_progress", "completed", "blocked"})
AGENT_KINDS = frozenset({"subagent", "worker", "coordinator"})
AGENT_RUN_STATUSES = frozenset({"created", "running", "completed", "failed", "cancelled"})
MAX_TASKS_PER_PLAN = 50
MAX_TASK_FIELD_CHARS = 2000
MAX_TASK_DEPENDENCIES = 20
MAX_AGENT_RUNS_PER_SESSION = 100
MAX_AGENT_FIELD_CHARS = 2000


class InMemorySessionStore:
    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}

    def load(self, session_id: str) -> SessionState:
        return self._states.get(session_id, SessionState())

    def save(self, session_id: str, state: SessionState) -> None:
        self._states = {**self._states, session_id: state}


class FileSessionStore:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def load(self, session_id: str) -> SessionState:
        path = self._path_for(session_id)
        if not path.exists():
            return SessionState()

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return _deserialize_session_state(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise SessionError(f"failed to load session: {session_id}") from error

    def save(self, session_id: str, state: SessionState) -> None:
        path = self._path_for(session_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(_serialize_session_state(state), ensure_ascii=False, indent=2)
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


def _serialize_session_state(state: SessionState) -> dict[str, object]:
    return {
        "messages": [asdict(message) for message in state.messages],
        "task_plan": _serialize_task_plan(state.task_plan),
        "context_state": _serialize_context_state(state.context_state),
        "agent_runs": [_serialize_agent_run_record(agent_run) for agent_run in state.agent_runs],
    }


def _deserialize_session_state(payload: object) -> SessionState:
    if not isinstance(payload, dict):
        raise ValueError("session state must be an object")
    messages = payload["messages"]
    task_plan = payload.get("task_plan")
    context_state = payload.get("context_state")
    agent_runs = payload.get("agent_runs", [])
    if not isinstance(messages, list):
        raise ValueError("session messages must be a list")
    if not isinstance(agent_runs, list):
        raise ValueError("session agent_runs must be a list")
    if len(agent_runs) > MAX_AGENT_RUNS_PER_SESSION:
        raise ValueError("session has too many agent runs")
    return SessionState(
        messages=tuple(_deserialize_message(item) for item in messages),
        task_plan=_deserialize_task_plan(task_plan),
        context_state=_deserialize_context_state(context_state),
        agent_runs=tuple(_deserialize_agent_run_record(item) for item in agent_runs),
    )


def _serialize_task_plan(task_plan: TaskPlan | None) -> dict[str, object] | None:
    if task_plan is None:
        return None
    return {"tasks": [_serialize_task(task) for task in task_plan.tasks]}


def _deserialize_task_plan(payload: object) -> TaskPlan | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("task plan must be an object")
    tasks_payload = payload["tasks"]
    if not isinstance(tasks_payload, list):
        raise ValueError("task plan tasks must be a list")
    task_plan = TaskPlan(tasks=tuple(_deserialize_task(item) for item in tasks_payload))
    validate_task_plan(task_plan, allow_empty=True)
    return task_plan


def _serialize_task(task: Task) -> dict[str, object]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "dependencies": list(task.dependencies),
        "attempts": task.attempts,
        "last_error": task.last_error,
    }


def _serialize_agent_run_record(record: AgentRunRecord) -> dict[str, object]:
    return {
        "agent_id": record.agent_id,
        "session_id": record.session_id,
        "name": record.name,
        "description": record.description,
        "kind": record.kind,
        "status": record.status,
        "result_summary": record.result_summary,
        "error": record.error,
    }


def _deserialize_agent_run_record(payload: object) -> AgentRunRecord:
    if not isinstance(payload, dict):
        raise ValueError("agent run must be an object")
    agent_id = payload["agent_id"]
    session_id = payload["session_id"]
    name = payload["name"]
    description = payload["description"]
    kind = payload["kind"]
    status = payload["status"]
    result_summary = payload.get("result_summary")
    error = payload.get("error")
    for field_name, value in {
        "agent_id": agent_id,
        "session_id": session_id,
        "name": name,
        "description": description,
    }.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"agent run {field_name} must be a non-empty string")
        if len(value) > MAX_AGENT_FIELD_CHARS:
            raise ValueError(f"agent run {field_name} is too long")
    if kind not in AGENT_KINDS:
        raise ValueError("agent run kind is invalid")
    if status not in AGENT_RUN_STATUSES:
        raise ValueError("agent run status is invalid")
    if result_summary is not None and not isinstance(result_summary, str):
        raise ValueError("agent run result_summary must be a string")
    if error is not None and not isinstance(error, str):
        raise ValueError("agent run error must be a string")
    if result_summary is not None and len(result_summary) > MAX_AGENT_FIELD_CHARS:
        raise ValueError("agent run result_summary is too long")
    if error is not None and len(error) > MAX_AGENT_FIELD_CHARS:
        raise ValueError("agent run error is too long")
    return AgentRunRecord(
        agent_id=agent_id,
        session_id=session_id,
        name=name,
        description=description,
        kind=kind,
        status=status,
        result_summary=result_summary,
        error=error,
    )


def _deserialize_task(payload: object) -> Task:
    if not isinstance(payload, dict):
        raise ValueError("task must be an object")
    task_id = payload["id"]
    title = payload["title"]
    description = payload["description"]
    status = payload.get("status", "pending")
    dependencies = payload.get("dependencies", [])
    attempts = payload.get("attempts", 0)
    last_error = payload.get("last_error")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task id must be a non-empty string")
    if not isinstance(title, str) or not title:
        raise ValueError("task title must be a non-empty string")
    if not isinstance(description, str):
        raise ValueError("task description must be a string")
    if status not in TASK_STATUSES:
        raise ValueError("task status is invalid")
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        raise ValueError("task dependencies must be strings")
    if not isinstance(attempts, int) or attempts < 0:
        raise ValueError("task attempts must be a non-negative integer")
    if last_error is not None and not isinstance(last_error, str):
        raise ValueError("task last_error must be a string")
    return Task(
        id=task_id,
        title=title,
        description=description,
        status=status,
        dependencies=tuple(dependencies),
        attempts=attempts,
        last_error=last_error,
    )


def validate_task_plan(task_plan: TaskPlan, *, allow_empty: bool = False) -> None:
    if not allow_empty and not task_plan.tasks:
        raise ValueError("task plan must include at least one task")
    if len(task_plan.tasks) > MAX_TASKS_PER_PLAN:
        raise ValueError("task plan has too many tasks")
    task_ids = tuple(task.id for task in task_plan.tasks)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be unique")
    known_ids = frozenset(task_ids)
    for task in task_plan.tasks:
        if not task.id:
            raise ValueError("task id must be a non-empty string")
        if len(task.id) > MAX_TASK_FIELD_CHARS:
            raise ValueError("task id is too long")
        if not task.title:
            raise ValueError("task title must be a non-empty string")
        if len(task.title) > MAX_TASK_FIELD_CHARS:
            raise ValueError("task title is too long")
        if len(task.description) > MAX_TASK_FIELD_CHARS:
            raise ValueError("task description is too long")
        if task.last_error is not None and len(task.last_error) > MAX_TASK_FIELD_CHARS:
            raise ValueError("task last_error is too long")
        if len(task.dependencies) > MAX_TASK_DEPENDENCIES:
            raise ValueError("task has too many dependencies")
        if task.status not in TASK_STATUSES:
            raise ValueError("task status is invalid")
        if task.id in task.dependencies:
            raise ValueError("task cannot depend on itself")
        unknown_dependencies = tuple(
            dependency for dependency in task.dependencies if dependency not in known_ids
        )
        if unknown_dependencies:
            raise ValueError("task dependency is unknown")
    _validate_task_plan_is_acyclic(task_plan)


def _validate_task_plan_is_acyclic(task_plan: TaskPlan) -> None:
    dependencies_by_id = {task.id: task.dependencies for task in task_plan.tasks}
    visiting: frozenset[str] = frozenset()
    visited: frozenset[str] = frozenset()
    for task in task_plan.tasks:
        if task.id not in visited:
            visited = _visit_task_dependencies(
                task_id=task.id,
                dependencies_by_id=dependencies_by_id,
                visiting=visiting,
                visited=visited,
            )


def _visit_task_dependencies(
    *,
    task_id: str,
    dependencies_by_id: dict[str, tuple[str, ...]],
    visiting: frozenset[str],
    visited: frozenset[str],
) -> frozenset[str]:
    if task_id in visiting:
        raise ValueError("task dependencies contain a cycle")
    if task_id in visited:
        return visited
    next_visiting = visiting | {task_id}
    next_visited = visited
    for dependency in dependencies_by_id[task_id]:
        next_visited = _visit_task_dependencies(
            task_id=dependency,
            dependencies_by_id=dependencies_by_id,
            visiting=next_visiting,
            visited=next_visited,
        )
    return next_visited | {task_id}


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
        tool_calls=tuple(
            _deserialize_tool_call(tool_call) for tool_call in item.get("tool_calls", ())
        ),
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


def _serialize_context_state(
    context_state: ContextManagementState | None,
) -> dict[str, object] | None:
    if context_state is None:
        return None
    return {
        "profile": context_state.profile,
        "version": context_state.version,
        "turn_count": context_state.turn_count,
        "latest_budget": _serialize_budget_snapshot(context_state.latest_budget),
        "auto_compaction": _serialize_auto_compaction_state(context_state.auto_compaction),
        "summary_snapshot": _serialize_summary_snapshot(context_state.summary_snapshot),
    }


def _deserialize_context_state(payload: object) -> ContextManagementState | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("context_state must be an object")
    profile = payload["profile"]
    version = payload["version"]
    turn_count = payload.get("turn_count", 0)
    if not isinstance(profile, str) or not profile:
        raise ValueError("context_state profile must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("context_state version must be a non-empty string")
    if not isinstance(turn_count, int) or turn_count < 0:
        raise ValueError("context_state turn_count must be a non-negative integer")
    return ContextManagementState(
        profile=profile,
        version=version,
        turn_count=turn_count,
        latest_budget=_deserialize_budget_snapshot(payload.get("latest_budget")),
        auto_compaction=_deserialize_auto_compaction_state(payload.get("auto_compaction")),
        summary_snapshot=_deserialize_summary_snapshot(payload.get("summary_snapshot")),
    )


def _serialize_budget_snapshot(snapshot: BudgetSnapshot | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "estimated_tokens_used": snapshot.estimated_tokens_used,
        "estimated_tokens_limit": snapshot.estimated_tokens_limit,
        "fill_ratio": snapshot.fill_ratio,
        "profile": snapshot.profile,
        "version": snapshot.version,
    }


def _deserialize_budget_snapshot(payload: object) -> BudgetSnapshot | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("budget snapshot must be an object")
    estimated_tokens_used = payload["estimated_tokens_used"]
    estimated_tokens_limit = payload["estimated_tokens_limit"]
    fill_ratio = payload["fill_ratio"]
    profile = payload["profile"]
    version = payload["version"]
    if not isinstance(estimated_tokens_used, int) or estimated_tokens_used < 0:
        raise ValueError("budget snapshot estimated_tokens_used must be a non-negative integer")
    if not isinstance(estimated_tokens_limit, int) or estimated_tokens_limit < 1:
        raise ValueError("budget snapshot estimated_tokens_limit must be >= 1")
    if not isinstance(fill_ratio, (int, float)) or fill_ratio < 0:
        raise ValueError("budget snapshot fill_ratio must be non-negative")
    if not isinstance(profile, str) or not profile:
        raise ValueError("budget snapshot profile must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("budget snapshot version must be a non-empty string")
    return BudgetSnapshot(
        estimated_tokens_used=estimated_tokens_used,
        estimated_tokens_limit=estimated_tokens_limit,
        fill_ratio=float(fill_ratio),
        profile=profile,
        version=version,
    )


def _serialize_auto_compaction_state(state: AutoCompactionState) -> dict[str, object]:
    return {
        "fail_streak": state.fail_streak,
        "last_fill_ratio": state.last_fill_ratio,
        "circuit_open": state.circuit_open,
        "last_error": state.last_error,
        "last_compacted_turn": state.last_compacted_turn,
    }


def _deserialize_auto_compaction_state(payload: object) -> AutoCompactionState:
    if payload is None:
        return AutoCompactionState()
    if not isinstance(payload, dict):
        raise ValueError("auto_compaction must be an object")
    fail_streak = payload.get("fail_streak", 0)
    last_fill_ratio = payload.get("last_fill_ratio")
    circuit_open = payload.get("circuit_open", False)
    last_error = payload.get("last_error")
    last_compacted_turn = payload.get("last_compacted_turn")
    if not isinstance(fail_streak, int) or fail_streak < 0:
        raise ValueError("auto_compaction fail_streak must be a non-negative integer")
    if last_fill_ratio is not None and (
        not isinstance(last_fill_ratio, (int, float)) or last_fill_ratio < 0
    ):
        raise ValueError("auto_compaction last_fill_ratio must be non-negative")
    if not isinstance(circuit_open, bool):
        raise ValueError("auto_compaction circuit_open must be a boolean")
    if last_error is not None and not isinstance(last_error, str):
        raise ValueError("auto_compaction last_error must be a string")
    if last_compacted_turn is not None and (
        not isinstance(last_compacted_turn, int) or last_compacted_turn < 0
    ):
        raise ValueError("auto_compaction last_compacted_turn must be a non-negative integer")
    return AutoCompactionState(
        fail_streak=fail_streak,
        last_fill_ratio=float(last_fill_ratio) if last_fill_ratio is not None else None,
        circuit_open=circuit_open,
        last_error=last_error,
        last_compacted_turn=last_compacted_turn,
    )


def _serialize_summary_snapshot(
    snapshot: CompactionSummarySnapshot | None,
) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "profile": snapshot.profile,
        "version": snapshot.version,
        "summary_text": snapshot.summary_text,
        "intent": snapshot.intent,
        "concepts": list(snapshot.concepts),
        "files": list(snapshot.files),
        "errors": list(snapshot.errors),
        "message_highlights": list(snapshot.message_highlights),
        "tasks": list(snapshot.tasks),
        "current_focus": snapshot.current_focus,
        "environment": list(snapshot.environment),
        "kept_conclusions": list(snapshot.kept_conclusions),
        "source_message_count": snapshot.source_message_count,
    }


def _deserialize_summary_snapshot(payload: object) -> CompactionSummarySnapshot | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("summary snapshot must be an object")
    profile = payload["profile"]
    version = payload["version"]
    summary_text = payload["summary_text"]
    intent = payload["intent"]
    concepts = payload.get("concepts", [])
    files = payload.get("files", [])
    errors = payload.get("errors", [])
    message_highlights = payload.get("message_highlights", [])
    tasks = payload.get("tasks", [])
    current_focus = payload.get("current_focus")
    environment = payload.get("environment", [])
    kept_conclusions = payload.get("kept_conclusions", [])
    source_message_count = payload.get("source_message_count", 0)
    if not isinstance(profile, str) or not profile:
        raise ValueError("summary snapshot profile must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ValueError("summary snapshot version must be a non-empty string")
    if not isinstance(summary_text, str):
        raise ValueError("summary snapshot summary_text must be a string")
    if not isinstance(intent, str):
        raise ValueError("summary snapshot intent must be a string")
    for field_name, value in {
        "concepts": concepts,
        "files": files,
        "errors": errors,
        "message_highlights": message_highlights,
        "tasks": tasks,
        "environment": environment,
        "kept_conclusions": kept_conclusions,
    }.items():
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"summary snapshot {field_name} must be strings")
    if current_focus is not None and not isinstance(current_focus, str):
        raise ValueError("summary snapshot current_focus must be a string")
    if not isinstance(source_message_count, int) or source_message_count < 0:
        raise ValueError("summary snapshot source_message_count must be a non-negative integer")
    return CompactionSummarySnapshot(
        profile=profile,
        version=version,
        summary_text=summary_text,
        intent=intent,
        concepts=tuple(concepts),
        files=tuple(files),
        errors=tuple(errors),
        message_highlights=tuple(message_highlights),
        tasks=tuple(tasks),
        current_focus=current_focus,
        environment=tuple(environment),
        kept_conclusions=tuple(kept_conclusions),
        source_message_count=source_message_count,
    )
