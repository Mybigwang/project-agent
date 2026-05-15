from __future__ import annotations

from pathlib import Path

from project_agent.core.types import MemoryFile
from project_agent.errors import ConfigurationError
from project_agent.runtime.memory.prompt import ENTRYPOINT_NAME

MANIFEST_READ_CHARS = 4096
DESCRIPTION_MAX_CHARS = 200


class FileMemoryStore:
    def __init__(self, *, memory_dir: Path) -> None:
        self.memory_dir = memory_dir.resolve()

    def ensure_initialized(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        entrypoint = self.memory_dir / ENTRYPOINT_NAME
        entrypoint.touch(exist_ok=True)

    def read_entrypoint(self, *, max_lines: int, max_bytes: int) -> tuple[str, bool]:
        path = self._resolve_inside(self.memory_dir / ENTRYPOINT_NAME)
        if not path.exists():
            return "", False
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return "", False
        return _truncate_by_lines_and_bytes(content, max_lines=max_lines, max_bytes=max_bytes)

    def scan_memory_files(self, *, max_files: int) -> tuple[MemoryFile, ...]:
        if not self.memory_dir.exists():
            return ()
        files: tuple[MemoryFile, ...] = ()
        for path in sorted(self.memory_dir.rglob("*.md")):
            resolved = self._resolve_inside(path)
            if resolved.name == ENTRYPOINT_NAME:
                continue
            memory_file = self._try_build_memory_file(resolved)
            if memory_file is None:
                continue
            files = (*files, memory_file)
            if len(files) >= max_files:
                break
        return files

    def read_memory_file(self, file: MemoryFile, *, max_chars: int) -> tuple[str, bool]:
        path = self._resolve_inside(file.path)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return "", False
        if len(content) <= max_chars:
            return content, False
        return content[:max_chars], True

    def _try_build_memory_file(self, path: Path) -> MemoryFile | None:
        try:
            content = path.read_text(encoding="utf-8")[:MANIFEST_READ_CHARS]
        except (OSError, UnicodeDecodeError):
            return None
        title, description = _extract_manifest(content, path.stem)
        return MemoryFile(
            path=path,
            relative_path=path.relative_to(self.memory_dir).as_posix(),
            title=title,
            description=description,
            mtime=path.stat().st_mtime,
        )

    def _resolve_inside(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.memory_dir)
        except ValueError as error:
            raise ConfigurationError("memory file path must be within memory_dir") from error
        return resolved


def _truncate_by_lines_and_bytes(content: str, *, max_lines: int, max_bytes: int) -> tuple[str, bool]:
    lines = content.splitlines()
    truncated = len(lines) > max_lines
    selected = "\n".join(lines[:max_lines])
    encoded = selected.encode("utf-8")
    if len(encoded) <= max_bytes:
        return selected, truncated
    truncated_bytes = encoded[:max_bytes]
    return truncated_bytes.decode("utf-8", errors="ignore"), True


def _extract_manifest(content: str, fallback_title: str) -> tuple[str, str]:
    title = fallback_title
    description = ""
    seen_title = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading and not seen_title:
                title = heading
                seen_title = True
            continue
        description = line[:DESCRIPTION_MAX_CHARS]
        break
    return title, description
