from collections.abc import Sequence
from pathlib import Path

from project_agent.core.interfaces import ModelClient, Plugin, SessionStore, Tool
from project_agent.core.types import Message, ToolCall, ToolResult


class ExamplePlugin:
    name = "example"

    def setup(self) -> None:
        return None


class ExampleTool:
    name = "echo"
    description = "Echo back content"
    input_schema = {"type": "object"}
    is_read_only = True

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(name=self.name, content=str(arguments.get("content", "")))


class ExampleModel:
    name = "example-model"

    def complete(self, *, messages: Sequence[Message], tools: Sequence[Tool]) -> Message | ToolCall:
        if tools:
            return ToolCall(name=tools[0].name)
        return Message(role="assistant", content=messages[-1].content)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._store: dict[str, list[Message]] = {}

    def load(self, session_id: str) -> Sequence[Message]:
        return self._store.get(session_id, [])

    def save(self, session_id: str, messages: Sequence[Message]) -> None:
        self._store[session_id] = list(messages)


def test_protocol_examples_match_interfaces() -> None:
    plugin: Plugin = ExamplePlugin()
    tool: Tool = ExampleTool()
    model: ModelClient = ExampleModel()
    store: SessionStore = InMemorySessionStore()

    plugin.setup()
    result = tool.run(workspace_root=Path("."), arguments={"content": "hello"})
    reply = model.complete(messages=[Message(role="user", content="hello")], tools=[tool])
    store.save("session-1", [Message(role="user", content="hello")])

    assert result.content == "hello"
    assert isinstance(reply, ToolCall)
    assert reply.name == "echo"
    assert store.load("session-1")[0].content == "hello"
