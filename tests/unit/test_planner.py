from __future__ import annotations

import pytest

from project_agent.core.types import Message, Task, TaskPlan, ToolCall
from project_agent.errors import AgentError
from project_agent.runtime.planner import LLMPlanner, StaticPlanner
from project_agent.runtime.session_store import MAX_TASKS_PER_PLAN


class TextModelClient:
    name = "text-model"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: tuple[Message, ...] = ()

    def complete(self, *, messages: tuple[Message, ...], tools: tuple[object, ...]) -> Message:  # type: ignore[override]
        self.messages = tuple(messages)
        return Message(role="assistant", content=self.content)


class ToolCallModelClient:
    name = "tool-call-model"

    def complete(
        self, *, messages: tuple[Message, ...], tools: tuple[object, ...]
    ) -> tuple[ToolCall, ...]:  # type: ignore[override]
        return (ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),)


def test_static_planner_wraps_request_in_single_pending_task() -> None:
    planner = StaticPlanner()

    plan = planner.create_plan(user_input="fix bug", history=())

    assert plan == TaskPlan(
        tasks=(
            Task(
                id="task_1",
                title="fix bug",
                description="fix bug",
                status="pending",
            ),
        )
    )


def test_llm_planner_parses_valid_json_plan() -> None:
    model_client = TextModelClient(
        '{"tasks": ['
        '{"id": "task_1", "title": "Inspect", "description": "Inspect repo", '
        '"dependencies": []}, '
        '{"id": "task_2", "title": "Implement", "description": "Make change", '
        '"dependencies": ["task_1"]}]}'
    )
    planner = LLMPlanner(model_client=model_client)

    plan = planner.create_plan(
        user_input="make change", history=(Message(role="user", content="old"),)
    )

    assert [task.status for task in plan.tasks] == ["pending", "pending"]
    assert plan.tasks[1].dependencies == ("task_1",)
    assert model_client.messages[0].role == "system"


def test_llm_planner_includes_skill_catalog_in_planning_prompt() -> None:
    model_client = TextModelClient(
        '{"tasks": [{"id": "task_1", "title": "Inspect", "description": "Inspect repo", "dependencies": []}]}'
    )
    planner = LLMPlanner(
        model_client=model_client,
        skill_catalog="- debug-bug: debug issues | when_to_use: when a page is broken",
    )

    planner.create_plan(user_input="fix page", history=())

    assert "Available execution-time skills" in model_client.messages[0].content
    assert "debug-bug: debug issues" in model_client.messages[0].content
    assert "return only JSON" in model_client.messages[0].content


def test_llm_planner_includes_skill_catalog_in_replanning_prompt() -> None:
    model_client = TextModelClient(
        '{"tasks": [{"id": "task_1", "title": "Done", "description": "Done", "status": "completed"}]}'
    )
    planner = LLMPlanner(
        model_client=model_client,
        skill_catalog="- debug-bug: debug issues | when_to_use: when a page is broken",
    )
    original = TaskPlan(
        tasks=(Task(id="task_1", title="Done", description="Done", status="completed"),)
    )

    replanned = planner.replan_after_failure(
        user_input="fix page",
        history=(),
        task_plan=original,
        failed_task_id="task_1",
        error="boom",
    )

    assert replanned.tasks[0] == original.tasks[0]
    assert "Available execution-time skills" in model_client.messages[0].content
    assert "debug-bug: debug issues" in model_client.messages[0].content


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"tasks": [{"id": "", "title": "A", "description": "A"}]}',
        '{"tasks": [{"id": "task_1", "title": "", "description": "A"}]}',
        (
            '{"tasks": [{"id": "task_1", "title": "A", "description": "A"}, '
            '{"id": "task_1", "title": "B", "description": "B"}]}'
        ),
        (
            '{"tasks": [{"id": "task_1", "title": "A", '
            '"description": "A", "dependencies": ["missing"]}]}'
        ),
        (
            '{"tasks": ['
            + ",".join(
                f'{{"id": "task_{index}", "title": "A", "description": "A"}}'
                for index in range(MAX_TASKS_PER_PLAN + 1)
            )
            + "]}"
        ),
        ('{"tasks": [{"id": "task_1", "title": "' + ("A" * 2001) + '", "description": "A"}]}'),
    ],
)
def test_llm_planner_rejects_invalid_plan(content: str) -> None:
    planner = LLMPlanner(model_client=TextModelClient(content))

    with pytest.raises(AgentError):
        planner.create_plan(user_input="make change", history=())


def test_llm_planner_rejects_tool_call_response() -> None:
    planner = LLMPlanner(model_client=ToolCallModelClient())  # type: ignore[arg-type]

    with pytest.raises(AgentError, match="planner must return a message"):
        planner.create_plan(user_input="make change", history=())


def test_replan_preserves_completed_tasks_and_blocks_failed_task() -> None:
    original = TaskPlan(
        tasks=(
            Task(id="task_1", title="Done", description="Done", status="completed"),
            Task(id="task_2", title="Failing", description="Failing", status="in_progress"),
            Task(
                id="task_3",
                title="Dependent",
                description="Dependent",
                status="pending",
                dependencies=("task_2",),
            ),
        )
    )
    planner = StaticPlanner()

    replanned = planner.replan_after_failure(
        user_input="make change",
        history=(),
        task_plan=original,
        failed_task_id="task_2",
        error="boom",
    )

    assert replanned.tasks[0] == original.tasks[0]
    assert replanned.tasks[1].status == "blocked"
    assert replanned.tasks[1].last_error == "boom"
    assert replanned.tasks[2].status == "blocked"
