from collections.abc import Sequence
from pathlib import Path

from project_agent.core.interfaces import Tool
from project_agent.core.types import MemoryFile, Message, SkillCall, ToolCall
from project_agent.runtime.memory.recall import ModelMemoryRecall


class RecallModelClient:
    name = "recall-model"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: tuple[Message, ...] = ()
        self.tools: tuple[Tool, ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        stream_callback: object | None = None,
    ) -> Message | SkillCall | tuple[ToolCall, ...]:
        del stream_callback
        self.messages = tuple(messages)
        self.tools = tuple(tools)
        return Message(role="assistant", content=self.content)


def _memory_file(name: str, title: str, description: str, mtime: float) -> MemoryFile:
    return MemoryFile(
        path=Path(name),
        relative_path=name,
        title=title,
        description=description,
        mtime=mtime,
    )


def test_model_memory_recall_asks_model_with_manifest_and_selects_returned_files() -> (
    None
):
    auth = _memory_file("auth.md", "Authentication", "OAuth login decisions", 1)
    billing = _memory_file("billing.md", "Billing", "Invoices", 2)
    model_client = RecallModelClient('{"files":["auth.md"]}')
    recall = ModelMemoryRecall(model_client=model_client)

    selected = recall.select(
        query="How does OAuth work?", files=(auth, billing), max_files=3
    )

    assert selected == (auth,)
    assert model_client.tools == ()
    assert "Memory manifest" in model_client.messages[1].content
    assert "auth.md" in model_client.messages[1].content


def test_model_memory_recall_limits_results_and_ignores_unknown_files() -> None:
    first = _memory_file("a.md", "A", "First", 1)
    second = _memory_file("b.md", "B", "Second", 2)
    model_client = RecallModelClient('{"files":["missing.md","b.md","a.md"]}')
    recall = ModelMemoryRecall(model_client=model_client)

    selected = recall.select(query="anything", files=(first, second), max_files=1)

    assert selected == (second,)


def test_model_memory_recall_returns_empty_for_invalid_json() -> None:
    file = _memory_file("a.md", "A", "First", 1)
    recall = ModelMemoryRecall(model_client=RecallModelClient("not json"))

    selected = recall.select(query="anything", files=(file,), max_files=1)

    assert selected == ()


def test_model_memory_recall_returns_empty_without_files() -> None:
    model_client = RecallModelClient('{"files":["a.md"]}')
    recall = ModelMemoryRecall(model_client=model_client)

    selected = recall.select(query="anything", files=(), max_files=1)

    assert selected == ()
    assert model_client.messages == ()
