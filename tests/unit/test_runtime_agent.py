from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from project_agent.core.types import Message, RepositoryContext, ToolCall
from project_agent.errors import RuntimeLimitError
from project_agent.runtime.agent import AgentRuntime
from project_agent.runtime.model_clients import MockModelClient
from project_agent.runtime.session_store import InMemorySessionStore
from project_agent.runtime.tools import EchoTool


class BoomTool:
    name = "boom"
    description = "Raise an error"
    input_schema = {"type": "object"}
    is_read_only = False

    def run(self, *, workspace_root: Path, arguments: dict[str, object]):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")



class CapturingModelClient:
    name = "capturing-model"

    def __init__(self) -> None:
        self.messages: tuple[Message, ...] = ()

    def complete(self, *, messages: Sequence[Message], tools: Sequence[object]) -> Message:
        self.messages = tuple(messages)
        return Message(role="assistant", content="ok")


class ToolCallCapturingModelClient:
    name = "tool-call-capturing-model"

    def __init__(self) -> None:
        self.calls: tuple[tuple[Message, ...], ...] = ()

    def complete(self, *, messages: Sequence[Message], tools: Sequence[object]) -> Message | ToolCall:
        self.calls = (*self.calls, tuple(messages))
        if len(self.calls) == 1:
            return ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123")
        return Message(role="assistant", content="done")


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
        content='{"content": "echo: ping", "data": null, "error_code": null, "name": "echo", "retryable": false, "status": "ok"}',
        tool_call_id="call_123",
    )


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
        (Message(role="user", content="previous"), Message(role="assistant", content="old")),
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
    assert store.load("session-1")[0].role == "user"


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


def test_agent_runtime_raises_when_max_steps_is_exceeded(
    runtime: AgentRuntime,
    store: InMemorySessionStore,
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeLimitError, match="max_steps=1"):
        runtime.run_turn(
            session_id="session-1",
            user_input="loop forever",
            model_client=MockModelClient(),
            tools=[EchoTool()],
            session_store=store,
            workspace_root=tmp_path,
            max_steps=1,
        )
