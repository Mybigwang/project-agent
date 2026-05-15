from collections.abc import Sequence
from pathlib import Path

from project_agent.core.interfaces import Tool
from project_agent.core.types import Message, SkillCall, ToolCall
from project_agent.runtime.memory import (
    FileMemoryStore,
    MemoryContextBuilder,
    ModelMemoryRecall,
)


class RecallModelClient:
    name = "recall-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        stream_callback: object | None = None,
    ) -> Message | SkillCall | tuple[ToolCall, ...]:
        del messages, tools, stream_callback
        return Message(role="assistant", content='{"files":["auth.md"]}')


class EmptyRecallModelClient:
    name = "empty-recall-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        stream_callback: object | None = None,
    ) -> Message | SkillCall | tuple[ToolCall, ...]:
        del messages, tools, stream_callback
        return Message(role="assistant", content='{"files":[]}')


def test_memory_context_builder_builds_prompt_with_recalled_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "MEMORY.md").write_text(
        "- [Auth](auth.md) — login decisions", encoding="utf-8"
    )
    (tmp_path / "auth.md").write_text(
        "# Auth\n\nOAuth login decisions", encoding="utf-8"
    )
    builder = MemoryContextBuilder(
        store=FileMemoryStore(memory_dir=tmp_path),
        recall=ModelMemoryRecall(model_client=RecallModelClient()),
        entrypoint_max_lines=200,
        entrypoint_max_bytes=25000,
        max_relevant_files=3,
        max_relevant_file_chars=3000,
        max_manifest_files=50,
    )

    context = builder.build(user_input="explain oauth login")

    assert "- [Auth](auth.md)" in context.prompt
    assert "## Relevant memory: auth.md" in context.prompt
    assert tuple(file.relative_path for file in context.relevant_files) == ("auth.md",)


def test_memory_context_builder_initializes_empty_memory_dir(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    builder = MemoryContextBuilder(
        store=FileMemoryStore(memory_dir=memory_dir),
        recall=ModelMemoryRecall(model_client=EmptyRecallModelClient()),
        entrypoint_max_lines=200,
        entrypoint_max_bytes=25000,
        max_relevant_files=3,
        max_relevant_file_chars=3000,
        max_manifest_files=50,
    )

    context = builder.build(user_input="hello")

    assert (memory_dir / "MEMORY.md").exists()
    assert "MEMORY.md is currently empty" in context.prompt
