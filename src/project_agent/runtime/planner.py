from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from project_agent.core.interfaces import ModelClient
from project_agent.core.types import Message, Task, TaskPlan
from project_agent.errors import AgentError
from project_agent.runtime.session_store import validate_task_plan


class StaticPlanner:
    def create_plan(self, *, user_input: str, history: Sequence[Message]) -> TaskPlan:
        del history
        title = user_input.strip() or "Process request"
        return TaskPlan(
            tasks=(
                Task(
                    id="task_1",
                    title=title,
                    description=title,
                    status="pending",
                ),
            )
        )

    def replan_after_failure(
        self,
        *,
        user_input: str,
        history: Sequence[Message],
        task_plan: TaskPlan,
        failed_task_id: str,
        error: str,
    ) -> TaskPlan:
        del user_input, history
        tasks = tuple(
            _block_failed_or_dependent_task(
                task=task,
                failed_task_id=failed_task_id,
                error=error,
                completed_task_ids=_completed_task_ids(task_plan),
            )
            for task in task_plan.tasks
        )
        return TaskPlan(tasks=tasks)


class LLMPlanner:
    def __init__(self, *, model_client: ModelClient) -> None:
        self._model_client = model_client

    def create_plan(self, *, user_input: str, history: Sequence[Message]) -> TaskPlan:
        messages = _build_planning_messages(user_input=user_input, history=history)
        response = self._model_client.complete(messages=messages, tools=())
        if not isinstance(response, Message):
            raise AgentError("planner must return a message")
        return _parse_task_plan_json(response.content)

    def replan_after_failure(
        self,
        *,
        user_input: str,
        history: Sequence[Message],
        task_plan: TaskPlan,
        failed_task_id: str,
        error: str,
    ) -> TaskPlan:
        messages = _build_replanning_messages(
            user_input=user_input,
            history=history,
            task_plan=task_plan,
            failed_task_id=failed_task_id,
            error=error,
        )
        response = self._model_client.complete(messages=messages, tools=())
        if not isinstance(response, Message):
            raise AgentError("planner must return a message")
        replanned = _parse_task_plan_json(response.content)
        _validate_replan_preserves_completed_tasks(
            original=task_plan,
            replanned=replanned,
        )
        return replanned


def _format_skill_catalog_for_planner(skill_registry: object | None) -> str:
    if skill_registry is None or not hasattr(skill_registry, "catalog_entries"):
        return ""
    entries = skill_registry.catalog_entries()
    if not entries:
        return ""
    lines = ["\nAvailable execution-time skills:\n"]
    for entry in entries:
        when_to_use = f" | when_to_use: {entry.when_to_use}" if entry.when_to_use else ""
        lines.append(f"- {entry.name}: {entry.description}{when_to_use}")
    return "\n".join(lines)


def _build_planning_messages(*, user_input: str, history: Sequence[Message]) -> tuple[Message, ...]:
    previous_context = "\n".join(message.content for message in history if message.content)
    return (
        Message(
            role="system",
            content=(
                "Break the user request into a JSON task plan. Return only JSON "
                "with a tasks array. Each task must include id, title, "
                "description, and optional dependencies. Use statuses only when "
                "needed; default status is pending. If the request is simple "
                "and does not require multiple steps, return a single task."
                "Please note that if the user's request involves significant complex changes,"
                "please add review and fix tasks to the execution plan to ensure the plan's correctness and executability."
            ),
        ),
        Message(
            role="user",
            content=f"Previous context:\n{previous_context}\n\nUser request:\n{user_input}",
        ),
    )


def _build_replanning_messages(
    *,
    user_input: str,
    history: Sequence[Message],
    task_plan: TaskPlan,
    failed_task_id: str,
    error: str,
) -> tuple[Message, ...]:
    plan_json = json.dumps(
        _serialize_plan_for_prompt(task_plan), ensure_ascii=False, sort_keys=True
    )
    previous_context = "\n".join(message.content for message in history if message.content)
    return (
        Message(
            role="system",
            content=(
                "Revise the JSON task plan after a failed task. Return only JSON. "
                "Preserve completed tasks exactly. Only change the failed task "
                "and tasks depending on it."
            ),
        ),
        Message(
            role="user",
            content=(
                f"Previous context:\n{previous_context}\n\nUser request:\n{user_input}\n\n"
                f"Failed task: {failed_task_id}\nError: {error}\nCurrent plan:\n{plan_json}"
            ),
        ),
    )


def _parse_task_plan_json(content: str) -> TaskPlan:
    content = content.strip()
    if content.startswith("```json"):
        content = content.removeprefix("```json")
    elif content.startswith("```"):
        content = content.removeprefix("```")
    if content.endswith("```"):
        content = content.removesuffix("```")
    content = content.strip()

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise AgentError("planner response must be valid JSON") from error
    task_plan = _parse_task_plan_payload(payload)
    try:
        validate_task_plan(task_plan)
    except ValueError as error:
        raise AgentError(f"planner response is invalid: {error}") from error
    return task_plan


def _parse_task_plan_payload(payload: object) -> TaskPlan:
    if not isinstance(payload, dict):
        raise AgentError("planner response must be a JSON object")
    tasks_payload = payload.get("tasks")
    if not isinstance(tasks_payload, list):
        raise AgentError("planner response tasks must be a list")
    return TaskPlan(tasks=tuple(_parse_task_payload(task) for task in tasks_payload))


def _parse_task_payload(payload: object) -> Task:
    if not isinstance(payload, dict):
        raise AgentError("planner task must be an object")
    task_id = payload.get("id")
    title = payload.get("title")
    description = payload.get("description")
    status = payload.get("status", "pending")
    dependencies = payload.get("dependencies", [])
    attempts = payload.get("attempts", 0)
    last_error = payload.get("last_error")
    if (
        not isinstance(task_id, str)
        or not isinstance(title, str)
        or not isinstance(description, str)
    ):
        raise AgentError("planner task id, title, and description must be strings")
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        raise AgentError("planner task dependencies must be strings")
    if not isinstance(status, str) or status not in {
        "pending",
        "in_progress",
        "completed",
        "blocked",
    }:
        raise AgentError("planner task status is invalid")
    if not isinstance(attempts, int) or attempts < 0:
        raise AgentError("planner task attempts must be a non-negative integer")
    if last_error is not None and not isinstance(last_error, str):
        raise AgentError("planner task last_error must be a string")
    return Task(
        id=task_id,
        title=title,
        description=description,
        status=status,  # type: ignore[arg-type]
        dependencies=tuple(dependencies),
        attempts=attempts,
        last_error=last_error,
    )


def _validate_replan_preserves_completed_tasks(*, original: TaskPlan, replanned: TaskPlan) -> None:
    replanned_by_id = {task.id: task for task in replanned.tasks}
    for task in original.tasks:
        if task.status == "completed" and replanned_by_id.get(task.id) != task:
            raise AgentError("replan must preserve completed tasks")


def _block_failed_or_dependent_task(
    *,
    task: Task,
    failed_task_id: str,
    error: str,
    completed_task_ids: frozenset[str],
) -> Task:
    if task.status == "completed":
        return task
    if task.id == failed_task_id:
        return replace(task, status="blocked", last_error=error)
    if failed_task_id in task.dependencies or any(
        dependency not in completed_task_ids for dependency in task.dependencies
    ):
        return replace(task, status="blocked")
    return task


def _completed_task_ids(task_plan: TaskPlan) -> frozenset[str]:
    return frozenset(task.id for task in task_plan.tasks if task.status == "completed")


def _serialize_plan_for_prompt(task_plan: TaskPlan) -> dict[str, Any]:
    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "dependencies": list(task.dependencies),
                "attempts": task.attempts,
                "last_error": task.last_error,
            }
            for task in task_plan.tasks
        ]
    }
