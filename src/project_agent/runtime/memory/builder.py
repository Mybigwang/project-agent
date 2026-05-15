from __future__ import annotations

from project_agent.core.types import MemoryContext, MemoryFile
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
    ) -> None:
        self.store = store
        self.recall = recall
        self.entrypoint_max_lines = entrypoint_max_lines
        self.entrypoint_max_bytes = entrypoint_max_bytes
        self.max_relevant_files = max_relevant_files
        self.max_relevant_file_chars = max_relevant_file_chars
        self.max_manifest_files = max_manifest_files

    def build(self, *, user_input: str) -> MemoryContext:
        self.store.ensure_initialized()
        entrypoint_content, entrypoint_truncated = self.store.read_entrypoint(
            max_lines=self.entrypoint_max_lines,
            max_bytes=self.entrypoint_max_bytes,
        )
        files = self.store.scan_memory_files(max_files=self.max_manifest_files)
        relevant_files = self.recall.select(
            query=user_input,
            files=files,
            max_files=self.max_relevant_files,
        )
        relevant_sections = tuple(self._build_relevant_section(file) for file in relevant_files)
        return MemoryContext(
            prompt=build_memory_prompt(
                memory_dir=self.store.memory_dir,
                entrypoint_content=entrypoint_content,
                entrypoint_truncated=entrypoint_truncated,
                relevant_sections=relevant_sections,
            ),
            relevant_files=relevant_files,
        )

    def _build_relevant_section(self, file: MemoryFile) -> str:
        content, truncated = self.store.read_memory_file(
            file,
            max_chars=self.max_relevant_file_chars,
        )
        suffix = "\n\n[Memory file truncated]" if truncated else ""
        return f"## Relevant memory: {file.relative_path}\n\n{content}{suffix}"
