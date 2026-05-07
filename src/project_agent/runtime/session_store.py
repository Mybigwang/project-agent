from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from project_agent.core.types import Message, SessionState, Task, TaskPlan, ToolCall
from project_agent.errors import SessionError

SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
TASK_STATUSES = frozenset({"pending", "in_progress", "completed", "blocked"})
MAX_TASKS_PER_PLAN = 50
MAX_TASK_FIELD_CHARS = 2000
MAX_TASK_DEPENDENCIES = 20


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
    }


def _deserialize_session_state(payload: object) -> SessionState:
    if not isinstance(payload, dict):
        raise ValueError("session state must be an object")
    messages = payload["messages"]
    task_plan = payload.get("task_plan")
    if not isinstance(messages, list):
        raise ValueError("session messages must be a list")
    return SessionState(
        messages=tuple(_deserialize_message(item) for item in messages),
        task_plan=_deserialize_task_plan(task_plan),
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
