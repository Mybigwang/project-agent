from __future__ import annotations

import json
from collections.abc import Sequence

from project_agent.core.interfaces import ModelClient
from project_agent.core.types import MemoryFile, Message


class ModelMemoryRecall:
    def __init__(self, *, model_client: ModelClient) -> None:
        self.model_client = model_client

    def select(
        self,
        *,
        query: str,
        files: Sequence[MemoryFile],
        max_files: int,
    ) -> tuple[MemoryFile, ...]:
        if not files:
            return ()
        manifest = _format_manifest(files)
        response = self.model_client.complete(
            messages=(
                Message(
                    role="system",
                    content=(
                        "You select relevant memory files for the next agent turn. "
                        "Return JSON only in this exact shape: "
                        '{"files":["relative/path.md"]}. '
                        "Select only files from the manifest. "
                        "Select none when no memory is relevant."
                    ),
                ),
                Message(
                    role="user",
                    content=(
                        f"User input:\n{query}\n\n"
                        f"Maximum files: {max_files}\n\n"
                        f"Memory manifest:\n{manifest}"
                    ),
                ),
            ),
            tools=(),
        )
        if not isinstance(response, Message):
            return ()
        selected_paths = _parse_selected_paths(response.content)
        by_path = {file.relative_path: file for file in files}
        selected: tuple[MemoryFile, ...] = ()
        for path in selected_paths:
            file = by_path.get(path)
            if file is None or file in selected:
                continue
            selected = (*selected, file)
            if len(selected) >= max_files:
                break
        return selected


def _format_manifest(files: Sequence[MemoryFile]) -> str:
    lines: tuple[str, ...] = ()
    for file in files:
        lines = (
            *lines,
            (
                f"- path: {file.relative_path}\n"
                f"  title: {file.title}\n"
                f"  description: {file.description}"
            ),
        )
    return "\n".join(lines)


def _parse_selected_paths(content: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, dict):
        return ()
    files = parsed.get("files")
    if not isinstance(files, list):
        return ()
    return tuple(item for item in files if isinstance(item, str))
