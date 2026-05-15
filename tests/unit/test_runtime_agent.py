from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from project_agent.core.types import (
    ContextManagementState,
    MemoryContext,
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
from project_agent.runtime.permissions import (
    PermissionMode,
    PermissionPolicy,
    ToolPermissionCategory,
)
from project_agent.runtime.session_store import InMemorySessionStore
from project_agent.runtime.tool_registry import ToolRegistry
from project_agent.runtime.tools import EchoTool
from project_agent.skills import (
    SkillPromptPreprocessor,
    SkillRegistry,
    SkillRuntimeSettings,
    load_skills,
)


class BoomTool:
    name = "boom"
    description = "Raise an error"
    input_schema = {"type": "object"}
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

    def run(self, *, workspace_root: Path, arguments: dict[str, object]):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


class SideEffectTool:
    name = "side_effect"
    description = "Record side effects"
    input_schema = {"type": "object"}
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

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
            return (
                ToolCall(
                    name="echo", arguments={"content": "ping"}, call_id="call_123"
                ),
            )
        return Message(role="assistant", content="done")


class PlannedToolCallCapturingModelClient(ToolCallCapturingModelClient):
    name = "planned-tool-call-capturing-model"


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
                ToolCall(
                    name="echo", arguments={"content": "second"}, call_id="call_2"
                ),
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
                ToolCall(
                    name="side_effect",
                    arguments={"content": "mutate"},
                    call_id="call_2",
                ),
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
            rendered="repo context",
            workspace=None,
            git=None,
            rules=(),
            relevant_files=(),
        )


class EmptyRepositoryContextBuilder:
    def build(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        history: Sequence[Message],
    ) -> RepositoryContext:
        return RepositoryContext(
            rendered="", workspace=None, git=None, rules=(), relevant_files=()
        )


class StaticMemoryContextBuilder:
    def __init__(self) -> None:
        self.calls = 0

    def build(self, *, user_input: str) -> MemoryContext:
        self.calls += 1
        return MemoryContext(prompt=f"memory for {user_input}", relevant_files=())


class FailingMemoryContextBuilder:
    def build(self, *, user_input: str) -> MemoryContext:
        del user_input
        raise AgentError("memory recall failed")


class OSErrorMemoryContextBuilder:
    def build(self, *, user_input: str) -> MemoryContext:
        del user_input
        raise OSError("memory directory unavailable")


class PassthroughContextManager:
    def prepare_messages(
        self,
        *,
        messages: Sequence[Message],
        task_plan: TaskPlan | None,
        existing_state: ContextManagementState | None,
    ) -> tuple[tuple[Message, ...], ContextManagementState | None]:
        del task_plan
        return tuple(messages), existing_state or ContextManagementState(
            profile="compact-default", version="v1"
        )


class RecordingContextManager:
    def __init__(self) -> None:
        self.received_states: tuple[ContextManagementState | None, ...] = ()
        self.received_messages: tuple[tuple[Message, ...], ...] = ()

    def prepare_messages(
        self,
        *,
        messages: Sequence[Message],
        task_plan: TaskPlan | None,
        existing_state: ContextManagementState | None,
    ) -> tuple[tuple[Message, ...], ContextManagementState | None]:
        del task_plan
        self.received_states = (*self.received_states, existing_state)
        self.received_messages = (*self.received_messages, tuple(messages))
        next_turn_count = 1 if existing_state is None else existing_state.turn_count + 1
        return tuple(messages), ContextManagementState(
            profile="compact-default",
            version="v1",
            turn_count=next_turn_count,
        )


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
    context_manager = RecordingContextManager()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="use tool ping",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        context_manager=context_manager,
    )

    assert result.final_message.content == "done"
    assert len(model_client.calls) == 2
    assert len(context_manager.received_messages) == 2
    second_call_messages = model_client.calls[1]
    assert second_call_messages[-2] == Message(
        role="assistant",
        content="",
        tool_calls=(
            ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),
        ),
    )
    assert second_call_messages[-1] == Message(
        role="tool",
        content=(
            '{"content": "echo: ping", "data": null, "error_code": null, '
            '"name": "echo", "retryable": false, "status": "ok"}'
        ),
        tool_call_id="call_123",
    )
    assert context_manager.received_messages[1][-2] == second_call_messages[-2]
    assert context_manager.received_messages[1][-1] == second_call_messages[-1]


def test_agent_runtime_executes_multiple_tool_calls_from_one_model_response(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = MultiToolCallCapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="use multiple tools",
        model_client=model_client,
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
        model_client=MultiToolCallWithErrorModelClient(),
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
        model_client=model_client,
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


def test_agent_runtime_injects_memory_context(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = CapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        memory_context_builder=StaticMemoryContextBuilder(),
    )

    assert result.memory_context is not None
    assert result.memory_context.prompt == "memory for hello"
    assert model_client.messages[0] == Message(
        role="system", content="memory for hello"
    )


def test_agent_runtime_continues_when_memory_context_build_fails(
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
        memory_context_builder=FailingMemoryContextBuilder(),
    )

    assert result.final_message.content == "Mock response (turn 1): hello"
    assert result.memory_context is None



def test_agent_runtime_continues_when_memory_context_build_raises_os_error(
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
        memory_context_builder=OSErrorMemoryContextBuilder(),
    )

    assert result.final_message.content == "Mock response (turn 1): hello"
    assert result.memory_context is None



def test_agent_runtime_orders_repository_memory_and_skill_system_messages(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    skill_registry = SkillRegistry(())
    model_client = CapturingModelClient()

    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        repository_context_builder=StaticRepositoryContextBuilder(),
        memory_context_builder=StaticMemoryContextBuilder(),
        skill_registry=skill_registry,
    )

    assert [message.content for message in model_client.messages[:2]] == [
        "repo context",
        "memory for hello",
    ]


def test_agent_runtime_context_manager_receives_memory_messages(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    context_manager = RecordingContextManager()

    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=CapturingModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        memory_context_builder=StaticMemoryContextBuilder(),
        context_manager=context_manager,
    )

    assert context_manager.received_messages[0][0] == Message(
        role="system", content="memory for hello"
    )


def test_agent_runtime_reinjects_memory_after_tool_result(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = ToolCallCapturingModelClient()
    context_manager = RecordingContextManager()
    memory_builder = StaticMemoryContextBuilder()

    runtime.run_turn(
        session_id="session-1",
        user_input="use tool ping",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        memory_context_builder=memory_builder,
        context_manager=context_manager,
    )

    assert memory_builder.calls == 1
    assert len(context_manager.received_messages) == 2
    assert context_manager.received_messages[1][0] == Message(
        role="system",
        content="memory for use tool ping",
    )


def test_agent_runtime_skips_repository_context_when_disabled(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    model_client = CapturingModelClient()

    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,
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
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        repository_context_builder=EmptyRepositoryContextBuilder(),
        enable_repository_context=True,
    )

    assert [message.role for message in model_client.messages] == ["user"]


def test_agent_runtime_reinjects_memory_after_tool_result_in_planned_task(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    planner = SequencePlanner(
        TaskPlan(tasks=(Task(id="task_1", title="First", description="First"),))
    )
    model_client = PlannedToolCallCapturingModelClient()
    context_manager = RecordingContextManager()
    memory_builder = StaticMemoryContextBuilder()

    runtime.run_turn(
        session_id="session-1",
        user_input="use tool ping",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
        memory_context_builder=memory_builder,
        context_manager=context_manager,
    )

    assert memory_builder.calls == 1
    assert len(model_client.calls) == 2
    assert context_manager.received_messages[1][1] == Message(
        role="system",
        content="memory for use tool ping",
    )


def test_agent_runtime_persists_context_state_from_context_manager(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=CapturingModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        context_manager=PassthroughContextManager(),
    )

    context_state = store.load("session-1").context_state
    assert context_state is not None
    assert context_state.profile == "compact-default"


def test_agent_runtime_propagates_context_state_across_planned_tasks(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    planner = SequencePlanner(
        TaskPlan(
            tasks=(
                Task(id="task_1", title="First", description="First"),
                Task(
                    id="task_2",
                    title="Second",
                    description="Second",
                    dependencies=("task_1",),
                ),
            )
        )
    )
    context_manager = RecordingContextManager()

    runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=CapturingModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
        memory_context_builder=StaticMemoryContextBuilder(),
        context_manager=context_manager,
    )

    assert len(context_manager.received_states) == 2
    assert context_manager.received_states[0] is None
    assert context_manager.received_states[1] is not None
    assert context_manager.received_states[1].turn_count == 1
    assert context_manager.received_messages[0][0].content.startswith(
        "Execute the current task."
    )
    assert context_manager.received_messages[0][1] == Message(
        role="system", content="memory for hello"
    )
    assert context_manager.received_messages[1][0].content.startswith(
        "Execute the current task."
    )
    assert context_manager.received_messages[1][1] == Message(
        role="system", content="memory for hello"
    )
    context_state = store.load("session-1").context_state
    assert context_state is not None
    assert context_state.turn_count == 2


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
                (
                    task
                    if task.status == "completed"
                    else Task(
                        id=task.id,
                        title=task.title,
                        description=task.description,
                        status="blocked",
                        dependencies=task.dependencies,
                        attempts=task.attempts,
                        last_error=(
                            error if task.id == failed_task_id else task.last_error
                        ),
                    )
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
                Task(
                    id="task_2",
                    title="Second",
                    description="Second",
                    dependencies=("task_1",),
                ),
            )
        )
    )
    model_client = CapturingModelClient()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="hello",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
    )

    assert result.final_message.content == "ok"
    assert result.task_plan is not None
    assert [task.status for task in result.task_plan.tasks] == [
        "completed",
        "completed",
    ]
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
        model_client=CapturingModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
    )

    assert planner.create_calls == 0
    assert result.task_plan is not None
    assert [task.id for task in result.task_plan.tasks] == ["task_1", "task_2"]
    assert [task.status for task in result.task_plan.tasks] == [
        "completed",
        "completed",
    ]


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
        model_client=CapturingModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=CountingPlanner(
            TaskPlan(tasks=(Task(id="new_task", title="New", description="New"),))
        ),
    )

    assert result.final_message.content == "ok"
    assert result.task_plan is not None
    assert [task.status for task in result.task_plan.tasks] == [
        "completed",
        "completed",
    ]


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
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=8,
        planner=planner,
    )

    assert planner.create_calls == 0
    assert model_client.messages == ()
    assert result.final_message.content == "No executable tasks remain."
    assert result.task_plan is not None
    assert result.task_plan.tasks[0].status == "blocked"
    assert result.task_plan.tasks[0].last_error == "boom"


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
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)
    model_client = SkillCallCapturingModelClient()
    context_manager = RecordingContextManager()

    result = runtime.run_turn(
        session_id="session-1",
        user_input="please review the change",
        model_client=model_client,
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        skill_registry=registry,
        skill_preprocessor=preprocessor,
        context_manager=context_manager,
    )

    assert result.final_message.content == "done"
    assert [step.event for step in result.trace] == ["skill", "assistant"]
    assert any(
        message.content.startswith("Activated skill: review-change")
        for message in result.messages
    )
    assert len(model_client.calls) == 2
    assert len(context_manager.received_messages) == 2
    assert any(
        message.role == "system" and "Review target src/module.py" in message.content
        for message in model_client.calls[1]
    )
    assert any(
        message.role == "system"
        and message.content.startswith("Activated skill: review-change")
        for message in context_manager.received_messages[1]
    )


def test_agent_runtime_emits_notification_for_model_selected_skill(
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
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)
    notifications: list[str] = []

    result = runtime.run_turn(
        session_id="session-1",
        user_input="please review the change",
        model_client=SkillCallCapturingModelClient(),
        tools=[EchoTool()],
        session_store=store,
        workspace_root=tmp_path,
        max_steps=3,
        notification_callback=notifications.append,
        skill_registry=registry,
        skill_preprocessor=preprocessor,
    )

    assert result.final_message.content == "done"
    assert notifications == ["正在调用 skill: review-change"]


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
            model_client=UnknownSkillCallModelClient(),
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
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(AgentError, match="non-selectable"):
        runtime.run_turn(
            session_id="session-1",
            user_input="please review the change",
            model_client=NonSelectableSkillCallModelClient(),
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
        (
            "---\nname: review-change\n"
            "description: review code changes\n---\n"
            "Review target {{args[0]}}"
        ),
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(AgentError, match="too many skills"):
        runtime.run_turn(
            session_id="session-1",
            user_input="please review the change",
            model_client=RepeatedSkillCallModelClient(),
            tools=[EchoTool()],
            session_store=store,
            workspace_root=tmp_path,
            max_steps=3,
            skill_registry=registry,
            skill_preprocessor=preprocessor,
        )


def test_agent_runtime_denies_tool_call_when_permission_policy_blocks_it(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    result = runtime._run_tool_call(
        tool_call=ToolCall(
            name="side_effect", arguments={"content": "x"}, call_id="call_1"
        ),
        registry=cli_tool_registry([SideEffectTool()]),
        workspace_root=tmp_path,
        permission_policy=PermissionPolicy(mode=PermissionMode.DONT_ASK),
        approval_callback=None,
    )

    assert result.is_error is True
    assert result.error_code == "permission_denied"
    assert result.data is not None
    assert result.data["reason_code"] is not None


def test_agent_runtime_requires_approval_without_callback_for_write_tool(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    result = runtime._run_tool_call(
        tool_call=ToolCall(
            name="side_effect", arguments={"content": "x"}, call_id="call_1"
        ),
        registry=cli_tool_registry([SideEffectTool()]),
        workspace_root=tmp_path,
        permission_policy=PermissionPolicy(mode=PermissionMode.DEFAULT),
        approval_callback=None,
    )

    assert result.is_error is True
    assert result.error_code == "permission_required"
    assert result.data is not None
    assert result.data["reason_code"] == "permission_write_requires_approval"


def cli_tool_registry(tools: Sequence[object]) -> ToolRegistry:
    return ToolRegistry(tools)  # type: ignore[arg-type]


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
