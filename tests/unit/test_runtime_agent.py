from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from project_agent.core.types import (
    Message,
    RepositoryContext,
    SessionState,
    SkillCall,
    Task,
    TaskPlan,
    ToolCall,
    ToolResult,
)
from project_agent.errors import AgentError
from project_agent.runtime.agent import AgentRuntime
from project_agent.runtime.model_clients import MockModelClient
from project_agent.runtime.session_store import InMemorySessionStore
from project_agent.runtime.tools import EchoTool
from project_agent.skills import SkillPromptPreprocessor, SkillRegistry, SkillRuntimeSettings, load_skills


class BoomTool:
    name = "boom"
    description = "Raise an error"
    input_schema = {"type": "object"}
    is_read_only = False

    def run(self, *, workspace_root: Path, arguments: dict[str, object]):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


class SideEffectTool:
    name = "side_effect"
    description = "Record side effects"
    input_schema = {"type": "object"}
    is_read_only = False

    def __init__(self) -> None:
        self.calls: tuple[str, ...] = ()

    def run(self, *, workspace_root: Path, arguments: dict[str, object]):  # type: ignore[no-untyped-def]
        del workspace_root
        content = arguments.get("content")
        if isinstance(content, str):
            self.calls = (*self.calls, content)
        return ToolResult(name=self.name, content=f"side effect: {content}")


class CapturingModelClient:
    name = "capturing-model"

    def __init__(self) -> None:
        self.messages: tuple[Message, ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> Message:
        del stream_callback
        self.messages = tuple(messages)
        return Message(role="assistant", content="ok")


class ToolCallCapturingModelClient:
    name = "tool-call-capturing-model"

    def __init__(self) -> None:
        self.calls: tuple[tuple[Message, ...], ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> Message | tuple[ToolCall, ...]:
        del tools, stream_callback
        self.calls = (*self.calls, tuple(messages))
        if len(self.calls) == 1:
            return (ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),)
        return Message(role="assistant", content="done")


class MultiToolCallCapturingModelClient:
    name = "multi-tool-call-capturing-model"

    def __init__(self) -> None:
        self.calls: tuple[tuple[Message, ...], ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> Message | tuple[ToolCall, ...]:
        del tools, stream_callback
        self.calls = (*self.calls, tuple(messages))
        if len(self.calls) == 1:
            return (
                ToolCall(name="echo", arguments={"content": "first"}, call_id="call_1"),
                ToolCall(name="echo", arguments={"content": "second"}, call_id="call_2"),
            )
        return Message(role="assistant", content="done")


class MultiToolCallWithErrorModelClient:
    name = "multi-tool-call-with-error-model"

    def __init__(self) -> None:
        self.calls: tuple[tuple[Message, ...], ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> Message | tuple[ToolCall, ...]:
        del tools, stream_callback
        self.calls = (*self.calls, tuple(messages))
        if len(self.calls) == 1:
            return (
                ToolCall(name="missing", arguments={}, call_id="call_1"),
                ToolCall(name="side_effect", arguments={"content": "mutate"}, call_id="call_2"),
            )
        return Message(role="assistant", content="done")


class SkillCallCapturingModelClient:
    name = "skill-call-capturing-model"

    def __init__(self) -> None:
        self.calls: tuple[tuple[Message, ...], ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> Message | SkillCall:
        del tools, stream_callback
        self.calls = (*self.calls, tuple(messages))
        if len(self.calls) == 1:
            return SkillCall(name="review-change", raw_args="src/module.py")
        return Message(role="assistant", content="done")


class RepeatedSkillCallModelClient:
    name = "repeated-skill-call-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> SkillCall:
        del messages, tools, stream_callback
        return SkillCall(name="review-change", raw_args="src/module.py")


class UnknownSkillCallModelClient:
    name = "unknown-skill-call-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> SkillCall:
        del messages, tools, stream_callback
        return SkillCall(name="missing-skill")


class NonSelectableSkillCallModelClient:
    name = "non-selectable-skill-call-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> SkillCall:
        del messages, tools, stream_callback
        return SkillCall(name="internal-review")



class StaticRepositoryContextBuilder:
    def build(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        history: Sequence[Message],
    ) -> RepositoryContext:
        return RepositoryContext(
            rendered="repo context", workspace=None, git=None, rules=(), relevant_files=()
        )


class EmptyRepositoryContextBuilder:
    def build(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        history: Sequence[Message],
    ) -> RepositoryContext:
        return RepositoryContext(rendered="", workspace=None, git=None, rules=(), relevant_files=())


@pytest.fixture
def runtime() -> AgentRuntime:
    return AgentRuntime()


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore()


def test_agent_runtime_returns_direct_model_message(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    result = runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=MockModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert result.final_message.content == "Mock response (turn 1): hello"
    assert result.messages[-1].role == "assistant"
    assert result.trace[-1].event == "assistant"


def test_agent_runtime_processes_tool_loop(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    result = runtime.run_turn(
        session_id="session-1",
        user_input="use tool ping",
        model_client=MockModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert result.final_message.content == "Tool result (turn 1): echo: ping"
    assert [step.event for step in result.trace] == ["tool", "assistant"]
    assert result.trace[0].tool_name == "echo"


def test_agent_runtime_preserves_tool_call_id_for_follow_up_request(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = ToolCallCapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="use tool ping",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert result.final_message.content == "done"
    assert len(model_client.calls) == 2
    second_call_messages = model_client.calls[1]
    assert second_call_messages[-2] == Message(
        role="assistant",
        content="",
        tool_calls=(ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),),
    )
    assert second_call_messages[-1] == Message(
        role="tool",
        content=(
            '{"content": "echo: ping", "data": null, "error_code": null, '
            '"name": "echo", "retryable": false, "status": "ok"}'
        ),
        tool_call_id="call_123",
    )


def test_agent_runtime_executes_multiple_tool_calls_from_one_model_response(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = MultiToolCallCapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="use multiple tools",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert result.final_message.content == "done"
    assert [step.summary for step in result.trace if step.event == "tool"] == [
        "echo: first",
        "echo: second",
    ]
    second_call_messages = model_client.calls[1]
    assert second_call_messages[-3] == Message(
        role="assistant",
        content="",
        tool_calls=(
            ToolCall(name="echo", arguments={"content": "first"}, call_id="call_1"),
            ToolCall(name="echo", arguments={"content": "second"}, call_id="call_2"),
        ),
    )
    assert second_call_messages[-2].role == "tool"
    assert second_call_messages[-2].tool_call_id == "call_1"
    assert second_call_messages[-1].role == "tool"
    assert second_call_messages[-1].tool_call_id == "call_2"


def test_agent_runtime_stops_multiple_tool_calls_after_first_error(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    side_effect_tool = SideEffectTool()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="use multiple tools with error",
        model_client=MultiToolCallWithErrorModelClient(),  # type: ignore[arg-type]
        tools=[EchoTool(), side_effect_tool],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert "tool not found: missing" in result.final_message.content
    assert side_effect_tool.calls == ()
    assert [step.summary for step in result.trace if step.event == "tool"] == [
        "tool not found: missing"
    ]


def test_agent_runtime_wraps_missing_tool_error(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    result = runtime.run_turn(
        session_id="session-1",
        user_input="missing tool",
        model_client=MockModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert "tool not found: missing" in result.final_message.content
    assert result.trace[0].is_error is True


def test_agent_runtime_wraps_tool_exception(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    result = runtime.run_turn(
        session_id="session-1",
        user_input="boom tool",
        model_client=MockModelClient(),
        tools=[EchoTool(), BoomTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
    )

    assert "tool execution failed: boom" in result.final_message.content
    assert result.trace[0].is_error is True


def test_agent_runtime_injects_repository_context_before_history_and_user_message(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    store.save(
        "session-1",
        SessionState(
            messages=(
                Message(role="user", content="previous"),
                Message(role="assistant", content="old"),
            )
        ),
    )
    model_client = CapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        repository_context_builder=StaticRepositoryContextBuilder(),
        enable_repository_context=True,
    )

    assert [message.role for message in model_client.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert model_client.messages[0].content == "repo context"
    assert result.messages == (
        Message(role="user", content="previous"),
        Message(role="assistant", content="old"),
        Message(role="user", content="hello"),
        Message(role="assistant", content="ok"),
    )
    assert store.load("session-1").messages[0].role == "user"


def test_agent_runtime_skips_repository_context_when_disabled(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = CapturingModelClient()

    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        repository_context_builder=StaticRepositoryContextBuilder(),
        enable_repository_context=False,
    )

    assert [message.role for message in model_client.messages] == ["user"]


def test_agent_runtime_skips_empty_repository_context(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = CapturingModelClient()

    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        repository_context_builder=EmptyRepositoryContextBuilder(),
        enable_repository_context=True,
    )

    assert [message.role for message in model_client.messages] == ["user"]


class AlwaysBoomModelClient:
    name = "always-boom-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[object],
        stream_callback: object | None = None,
    ) -> tuple[ToolCall, ...]:
        del messages, tools, stream_callback
        return (ToolCall(name="boom", arguments={}, call_id="call_boom"),)


class SequencePlanner:
    def __init__(self, task_plan: TaskPlan) -> None:
        self.task_plan = task_plan
        self.replans: tuple[tuple[str, str], ...] = ()

    def create_plan(self, *, user_input: str, history: Sequence[Message]) -> TaskPlan:
        return self.task_plan

    def replan_after_failure(
        self,
        *,
        user_input: str,
        history: Sequence[Message],
        task_plan: TaskPlan,
        failed_task_id: str,
        error: str,
    ) -> TaskPlan:
        self.replans = (*self.replans, (failed_task_id, error))
        return TaskPlan(
            tasks=tuple(
                task
                if task.status == "completed"
                else Task(
                    id=task.id,
                    title=task.title,
                    description=task.description,
                    status="blocked",
                    dependencies=task.dependencies,
                    attempts=task.attempts,
                    last_error=error if task.id == failed_task_id else task.last_error,
                )
                for task in task_plan.tasks
            )
        )


class CountingPlanner(SequencePlanner):
    def __init__(self, task_plan: TaskPlan) -> None:
        super().__init__(task_plan)
        self.create_calls = 0

    def create_plan(self, *, user_input: str, history: Sequence[Message]) -> TaskPlan:
        self.create_calls += 1
        return self.task_plan


def test_agent_runtime_executes_planned_tasks_and_persists_task_plan(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    planner = SequencePlanner(
        TaskPlan(
            tasks=(
                Task(id="task_1", title="First", description="First"),
                Task(id="task_2", title="Second", description="Second", dependencies=("task_1",)),
            )
        )
    )
    model_client = CapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
    )

    assert result.final_message.content == "ok"
    assert [task.status for task in result.task_plan.tasks] == ["completed", "completed"]  # type: ignore[union-attr]
    assert result.messages == (
        Message(role="user", content="hello"),
        Message(role="assistant", content="ok"),
        Message(role="assistant", content="ok"),
    )
    assert store.load("session-1").task_plan == result.task_plan
    assert [step.task_status for step in result.trace if step.event == "task"] == [
        "in_progress",
        "completed",
        "in_progress",
        "completed",
    ]


def test_agent_runtime_resumes_unfinished_session_task_plan(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    existing_plan = TaskPlan(
        tasks=(
            Task(id="task_1", title="Done", description="Done", status="completed"),
            Task(id="task_2", title="Resume", description="Resume"),
        )
    )
    store.save("session-1", SessionState(messages=(), task_plan=existing_plan))
    planner = CountingPlanner(
        TaskPlan(tasks=(Task(id="new_task", title="New", description="New"),))
    )

    result = runtime.run_turn(
        session_id="session-1",
        user_input="continue",
        model_client=CapturingModelClient(),  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
    )

    assert planner.create_calls == 0
    assert [task.id for task in result.task_plan.tasks] == ["task_1", "task_2"]  # type: ignore[union-attr]
    assert [task.status for task in result.task_plan.tasks] == ["completed", "completed"]  # type: ignore[union-attr]


def test_agent_runtime_unblocks_dependency_blocked_task_when_dependencies_complete(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    existing_plan = TaskPlan(
        tasks=(
            Task(id="task_1", title="Done", description="Done", status="completed"),
            Task(
                id="task_2",
                title="Resume",
                description="Resume",
                status="blocked",
                dependencies=("task_1",),
            ),
        )
    )
    store.save("session-1", SessionState(messages=(), task_plan=existing_plan))

    result = runtime.run_turn(
        session_id="session-1",
        user_input="continue",
        model_client=CapturingModelClient(),  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=CountingPlanner(
            TaskPlan(tasks=(Task(id="new_task", title="New", description="New"),))
        ),
    )

    assert result.final_message.content == "ok"
    assert [task.status for task in result.task_plan.tasks] == ["completed", "completed"]  # type: ignore[union-attr]


def test_agent_runtime_does_not_resume_failed_blocked_task(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    existing_plan = TaskPlan(
        tasks=(
            Task(
                id="task_1",
                title="Failed",
                description="Failed",
                status="blocked",
                last_error="boom",
            ),
        )
    )
    store.save("session-1", SessionState(messages=(), task_plan=existing_plan))
    planner = CountingPlanner(
        TaskPlan(tasks=(Task(id="new_task", title="New", description="New"),))
    )
    model_client = CapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="continue",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
    )

    assert planner.create_calls == 0
    assert model_client.messages == ()
    assert result.final_message.content == "No executable tasks remain."
    assert result.task_plan.tasks[0].status == "blocked"  # type: ignore[union-attr]
    assert result.task_plan.tasks[0].last_error == "boom"  # type: ignore[union-attr]




def test_agent_runtime_applies_model_selected_skill_and_continues(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / ".project_agent" / "skills"
    _write_skill(
        project_root / "review-change" / "SKILL.md",
        (
            "---\n"
            "name: review-change\n"
            "description: review code changes\n"
            "when_to_use: when the user asks for a review\n"
            "---\n"
            "Review target {{args[0]}}"
        ),
    )
    registry = SkillRegistry(load_skills(builtin_root=None, user_root=None, project_root=project_root))
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)
    model_client = SkillCallCapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="please review the change",
        model_client=model_client,  # type: ignore[arg-type]
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        skill_registry=registry,
        skill_preprocessor=preprocessor,
    )

    assert result.final_message.content == "done"
    assert [step.event for step in result.trace] == ["skill", "assistant"]
    assert any(message.content.startswith("Activated skill: review-change") for message in result.messages)
    assert len(model_client.calls) == 2
    assert any(
        message.role == "system" and "Review target src/module.py" in message.content
        for message in model_client.calls[1]
    )


def test_agent_runtime_rejects_unknown_model_selected_skill(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    registry = SkillRegistry(())
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(AgentError, match="unknown skill"):
        runtime.run_turn(
            session_id="session-1",
            user_input="please review the change",
            model_client=UnknownSkillCallModelClient(),  # type: ignore[arg-type]
            tools=[EchoTool()],
            session_store=store,
            workspace_root=tmp_path,
            max_steps=3,
            skill_registry=registry,
            skill_preprocessor=preprocessor,
        )


def test_agent_runtime_rejects_non_selectable_model_selected_skill(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / ".project_agent" / "skills"
    _write_skill(
        project_root / "internal-review" / "SKILL.md",
        (
            "---\n"
            "name: internal-review\n"
            "description: internal review\n"
            "user_invocable: false\n"
            "model_selectable: false\n"
            "---\n"
            "Internal review"
        ),
    )
    registry = SkillRegistry(load_skills(builtin_root=None, user_root=None, project_root=project_root))
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(AgentError, match="non-selectable"):
        runtime.run_turn(
            session_id="session-1",
            user_input="please review the change",
            model_client=NonSelectableSkillCallModelClient(),  # type: ignore[arg-type]
            tools=[EchoTool()],
            session_store=store,
            workspace_root=tmp_path,
            max_steps=3,
            skill_registry=registry,
            skill_preprocessor=preprocessor,
        )


def test_agent_runtime_rejects_repeated_skill_selection_in_one_turn(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / ".project_agent" / "skills"
    _write_skill(
        project_root / "review-change" / "SKILL.md",
        "---\nname: review-change\ndescription: review code changes\n---\nReview target {{args[0]}}",
    )
    registry = SkillRegistry(load_skills(builtin_root=None, user_root=None, project_root=project_root))
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(AgentError, match="too many skills"):
        runtime.run_turn(
            session_id="session-1",
            user_input="please review the change",
            model_client=RepeatedSkillCallModelClient(),  # type: ignore[arg-type]
            tools=[EchoTool()],
            session_store=store,
            workspace_root=tmp_path,
            max_steps=3,
            skill_registry=registry,
            skill_preprocessor=preprocessor,
        )


def _make_preprocessor(
    *,
    registry: SkillRegistry,
    workspace_root: Path,
) -> SkillPromptPreprocessor:
    return SkillPromptPreprocessor(
        registry=registry,
        workspace_root=workspace_root,
        max_composition_depth=3,
        max_expansion_chars=2000,
        runtime_settings=SkillRuntimeSettings(allow_command_substitution=False),
    )


def _write_skill(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
