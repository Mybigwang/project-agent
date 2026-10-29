from __future__ import annotations

from collections.abc import Sequence

from project_agent.core.types import MemoryContext, MemoryFile, Message
from project_agent.runtime.memory.prompt import build_memory_prompt
from project_agent.runtime.memory.recall import ModelMemoryRecall
from project_agent.runtime.memory.store import FileMemoryStore


class MemoryContextBuilder:
    def __init__(
        self,
        *,
        store: FileMemoryStore,
        recall: ModelMemoryRecall,
        entrypoint_max_lines: int,
        entrypoint_max_bytes: int,
        max_relevant_files: int,
        max_relevant_file_chars: int,
        max_manifest_files: int,
        max_unused_days: int = 30,
        prompt_max_chars: int = 12000,
    ) -> None:
        self.store = store
        self.recall = recall
        self.entrypoint_max_lines = entrypoint_max_lines
        self.entrypoint_max_bytes = entrypoint_max_bytes
        self.max_relevant_files = max_relevant_files
        self.max_relevant_file_chars = max_relevant_file_chars
        self.max_manifest_files = max_manifest_files
        self.max_unused_days = max_unused_days
        self.prompt_max_chars = prompt_max_chars

    def build(self, *, user_input: str, history: Sequence[Message] = ()) -> MemoryContext:
        self.store.ensure_initialized()
        self.store.archive_unused(max_unused_days=self.max_unused_days)
        entrypoint_content, entrypoint_truncated = self.store.read_entrypoint(
            max_lines=self.entrypoint_max_lines,
            max_bytes=self.entrypoint_max_bytes,
        )
        recent = "\n".join(m.content[:1000] for m in history[-6:] if m.role == "user")
        query = (
            f"Recent user context:\n{recent}\n\nCurrent request:\n{user_input}"
            if recent
            else user_input
        )
        files = self.store.scan_memory_files(max_files=self.max_manifest_files, query=query)
        relevant_files = self.recall.select(
            query=query,
            files=files,
            max_files=self.max_relevant_files,
        )
        if not relevant_files:
            archived = self.store.scan_memory_files(
                max_files=self.max_manifest_files,
                archived=True,
                query=query,
            )
            relevant_files = self.recall.select(
                query=query,
                files=archived,
                max_files=self.max_relevant_files,
            )
        relevant_sections = tuple(self._build_relevant_section(file) for file in relevant_files)
        while True:
            prompt = build_memory_prompt(
                memory_dir=self.store.memory_dir,
                entrypoint_content=entrypoint_content,
                entrypoint_truncated=entrypoint_truncated,
                relevant_sections=relevant_sections,
            )
            if len(prompt) <= self.prompt_max_chars or not relevant_files:
                break
            relevant_files = relevant_files[:-1]
            relevant_sections = relevant_sections[:-1]
        if len(prompt) > self.prompt_max_chars:
            prompt = prompt[: self.prompt_max_chars - 26] + "\n[Memory prompt truncated]"
        recorded = False

        def record(messages: Sequence[Message]) -> None:
            nonlocal recorded
            if recorded or not relevant_files:
                return
            delivered = tuple(
                file
                for file, section in zip(relevant_files, relevant_sections, strict=True)
                if any(section in m.content for m in messages if m.role == "system")
            )
            if delivered:
                self.store.record_recalled(delivered)
                recorded = True

        return MemoryContext(prompt=prompt, relevant_files=relevant_files, on_recalled=record)

    def _build_relevant_section(self, file: MemoryFile) -> str:
        content, truncated = self.store.read_memory_file(
            file,
            max_chars=self.max_relevant_file_chars,
        )
        suffix = "\n\n[Memory file truncated]" if truncated else ""
        return f"## Relevant memory: {file.relative_path}\n\n{content}{suffix}"
