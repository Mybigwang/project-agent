from collections.abc import Callable, Sequence
from pathlib import Path

from project_agent.core.interfaces import (
    CompactionSummaryBuilderProtocol,
    ContextBudgetEstimatorProtocol,
    ContextManagerProtocol,
    ModelClient,
    Plugin,
    SessionStore,
    Tool,
)
from project_agent.core.types import BudgetSnapshot, CompactionSummarySnapshot, ContextManagementState, Message, SessionState, SkillCall, ToolCall, ToolResult
from project_agent.runtime.permissions import ToolPermissionCategory


class ExamplePlugin:
    name = "example"

    def setup(self) -> None:
        return None


class ExampleTool:
    name = "echo"
    description = "Echo back content"
    input_schema = {"type": "object"}
    is_read_only = True
    permission_category = ToolPermissionCategory.READ

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(name=self.name, content=str(arguments.get("content", "")))


class ExampleModel:
    name = "example-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        stream_callback: Callable[[str], None] | None = None,
    ) -> Message | SkillCall | tuple[ToolCall, ...]:
        del stream_callback
        if tools:
            return (ToolCall(name=tools[0].name, call_id="call_echo"),)
        return Message(role="assistant", content=messages[-1].content)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._store: dict[str, SessionState] = {}

    def load(self, session_id: str) -> SessionState:
        return self._store.get(session_id, SessionState())

    def save(self, session_id: str, state: SessionState) -> None:
        self._store[session_id] = state


class ExampleBudgetEstimator:
    def estimate_messages(
        self,
        *,
        messages: Sequence[Message],
        token_limit: int,
        profile: str,
        version: str,
    ) -> BudgetSnapshot:
        return BudgetSnapshot(
            estimated_tokens_used=len(messages),
            estimated_tokens_limit=token_limit,
            fill_ratio=len(messages) / token_limit,
            profile=profile,
            version=version,
        )


class ExampleSummaryBuilder:
    def build_summary(
        self,
        *,
        messages: Sequence[Message],
        task_plan: object | None,
        existing_state: ContextManagementState | None,
    ) -> CompactionSummarySnapshot:
        del task_plan, existing_state
        return CompactionSummarySnapshot(
            profile="compact-default",
            version="v1",
            summary_text=messages[-1].content if messages else "",
            intent=messages[-1].content if messages else "",
        )


class ExampleContextManager:
    def prepare_messages(
        self,
        *,
        messages: Sequence[Message],
        task_plan: object | None,
        existing_state: ContextManagementState | None,
    ) -> tuple[tuple[Message, ...], ContextManagementState | None]:
        del task_plan
        state = existing_state or ContextManagementState(profile="compact-default", version="v1")
        return tuple(messages), state


def test_protocol_examples_match_interfaces() -> None:
    plugin: Plugin = ExamplePlugin()
    tool: Tool = ExampleTool()
    model: ModelClient = ExampleModel()
    store: SessionStore = InMemorySessionStore()
    budget_estimator: ContextBudgetEstimatorProtocol = ExampleBudgetEstimator()
    summary_builder: CompactionSummaryBuilderProtocol = ExampleSummaryBuilder()
    context_manager: ContextManagerProtocol = ExampleContextManager()

    plugin.setup()
    result = tool.run(workspace_root=Path("."), arguments={"content": "hello"})
    reply = model.complete(messages=[Message(role="user", content="hello")], tools=[tool])
    store.save("session-1", SessionState(messages=(Message(role="user", content="hello"),)))

    snapshot = budget_estimator.estimate_messages(
        messages=[Message(role="user", content="hello")],
        token_limit=10,
        profile="compact-default",
        version="v1",
    )
    summary = summary_builder.build_summary(
        messages=[Message(role="user", content="hello")],
        task_plan=None,
        existing_state=None,
    )
    prepared_messages, prepared_state = context_manager.prepare_messages(
        messages=[Message(role="user", content="hello")],
        task_plan=None,
        existing_state=None,
    )

    assert result.content == "hello"
    assert isinstance(reply, tuple)
    assert len(reply) == 1
    assert reply[0].name == "echo"
    assert store.load("session-1").messages[0].content == "hello"
    assert snapshot.estimated_tokens_used == 1
    assert summary.summary_text == "hello"
    assert prepared_messages[0].content == "hello"
    assert prepared_state is not None
