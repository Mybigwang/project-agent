from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from project_agent.core.types import MemoryFile
from project_agent.errors import ConfigurationError
from project_agent.runtime.memory.models import TopicUpdate, check_topic
from project_agent.runtime.memory.prompt import ENTRYPOINT_NAME
from project_agent.runtime.persistence import atomic_write, file_lock

MANIFEST_READ_CHARS = 4096
DESCRIPTION_MAX_CHARS = 200


class FileMemoryStore:
    def __init__(self, *, memory_dir: Path) -> None:
        self.memory_dir = memory_dir.resolve()

    def ensure_initialized(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        for directory in ("topics", "candidates"):
            self._resolve_inside(self.memory_dir / directory).mkdir(exist_ok=True)
        entrypoint = self._resolve_inside(self.memory_dir / ENTRYPOINT_NAME)
        if not entrypoint.exists():
            entrypoint.touch()

    def read_entrypoint(self, *, max_lines: int, max_bytes: int) -> tuple[str, bool]:
        path = self._resolve_inside(self.memory_dir / ENTRYPOINT_NAME)
        if not path.exists():
            return "", False
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return "", False
        return _truncate_by_lines_and_bytes(content, max_lines=max_lines, max_bytes=max_bytes)

    def scan_memory_files(
        self, *, max_files: int, archived: bool = False, query: str = ""
    ) -> tuple[MemoryFile, ...]:
        if not self.memory_dir.exists():
            return ()
        state = self.read_state()
        files: list[MemoryFile] = []
        for path in sorted(self._resolve_inside(self.memory_dir / "topics").glob("*.md")):
            resolved = self._resolve_inside(path)
            metadata = state["topics"].get(path.stem, {})
            if path.stem in state["forgotten"]:
                continue
            if (metadata.get("status", "active") == "archived") != archived:
                continue
            memory_file = self._try_build_memory_file(resolved)
            if memory_file is None:
                continue
            files.append(memory_file)
        # Prefer matching descriptions and recent use rather than alphabetical prefixes.
        words = query.lower().split()

        def rank(file: MemoryFile) -> tuple[int, int, float]:
            metadata = state["topics"].get(file.path.stem, {})
            description = f"{file.title} {file.description} {file.path.stem}".lower()
            matches = sum(word in description for word in words)
            return (
                int(metadata.get("pinned", False)),
                matches,
                float(metadata.get("last_recalled_at") or file.mtime),
            )

        return tuple(sorted(files, key=rank, reverse=True)[:max_files])

    def state_path(self) -> Path:
        return self._resolve_inside(self.memory_dir / "state.json")

    def lock_path(self, name: str = "state") -> Path:
        return self._resolve_inside(self.memory_dir / f".{name}.lock")

    def read_state(self) -> dict[str, Any]:
        path = self.state_path()
        if not path.exists():
            return {"topics": {}, "processed": {}, "forgotten": {}}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), dict) for key in ("topics", "processed", "forgotten")
        ):
            raise ConfigurationError("invalid memory state; restore state.json before writing")
        return value

    def _save_state(self, state: dict[str, Any]) -> None:
        atomic_write(self.state_path(), json.dumps(state, ensure_ascii=False, indent=2))

    def topic_path(self, topic: str) -> Path:
        return self._resolve_inside(self.memory_dir / "topics" / f"{check_topic(topic)}.md")

    def _register_topics(self, state: dict[str, Any]) -> None:
        for path in self._resolve_inside(self.memory_dir / "topics").glob("*.md"):
            self._resolve_inside(path)
            check_topic(path.stem)
            if path.stem not in state["topics"] and path.stem not in state["forgotten"]:
                state["topics"][path.stem] = {
                    "created_at": path.stat().st_mtime,
                    "updated_at": path.stat().st_mtime,
                    "last_recalled_at": None,
                    "status": "active",
                    "pinned": False,
                    "sources": [],
                }

    def _write_index(self, state: dict[str, Any]) -> None:
        lines = []
        for topic, metadata in sorted(state["topics"].items()):
            if metadata["status"] != "active" or topic in state["forgotten"]:
                continue
            file = self._try_build_memory_file(self.topic_path(topic))
            if file is not None:
                title = file.title.replace("[", "").replace("]", "")
                lines.append(f"- [{title}]({file.relative_path}) — {file.description}")
        atomic_write(self._resolve_inside(self.memory_dir / ENTRYPOINT_NAME), "\n".join(lines))

    def archive_unused(self, *, max_unused_days: int, now: float | None = None) -> int:
        self.ensure_initialized()
        now = time.time() if now is None else now
        count = 0
        with file_lock(self.lock_path(), blocking=True):
            state = self.read_state()
            self._register_topics(state)
            for metadata in state["topics"].values():
                last = max(
                    metadata["last_recalled_at"] or metadata["created_at"], metadata["updated_at"]
                )
                if (
                    metadata["status"] == "active"
                    and not metadata["pinned"]
                    and now - last >= max_unused_days * 86400
                ):
                    metadata["status"] = "archived"
                    count += 1
            self._save_state(state)
            self._write_index(state)
        return count

    def record_recalled(self, files: tuple[MemoryFile, ...], *, now: float | None = None) -> None:
        with file_lock(self.lock_path(), blocking=True):
            state = self.read_state()
            self._register_topics(state)
            for file in files:
                topic = file.path.stem
                if topic not in state["forgotten"] and topic in state["topics"]:
                    state["topics"][topic]["last_recalled_at"] = time.time() if now is None else now
                    state["topics"][topic]["status"] = "active"
            self._save_state(state)
            self._write_index(state)

    def snapshot(self, topics: tuple[str, ...]) -> dict[str, str]:
        with file_lock(self.lock_path(), blocking=True):
            contents = {}
            for topic in topics:
                path = self.topic_path(topic)
                contents[topic] = path.read_text(encoding="utf-8") if path.exists() else ""
            return contents

    def commit(
        self,
        updates: tuple[TopicUpdate, ...],
        *,
        expected: dict[str, str],
        explicit: bool = False,
    ) -> None:
        with file_lock(self.lock_path(), blocking=True):
            state = self.read_state()
            self._register_topics(state)
            for topic, previous in expected.items():
                path = self.topic_path(topic)
                current = path.read_text(encoding="utf-8") if path.exists() else ""
                if current != previous:
                    raise ConfigurationError("memory changed during consolidation; retry refresh")
            for update in updates:
                if update.topic in state["forgotten"] and not explicit:
                    raise ConfigurationError("forgotten topic cannot be regenerated automatically")
            for update in updates:
                state["forgotten"].pop(update.topic, None)
                metadata = state["topics"].setdefault(
                    update.topic,
                    {
                        "created_at": time.time(),
                        "updated_at": time.time(),
                        "last_recalled_at": None,
                        "status": "active",
                        "pinned": False,
                        "sources": [],
                    },
                )
                metadata["sources"] = sorted(set(metadata["sources"]) | set(update.sources))
                # A changed topic becomes available again; unchanged consolidation is not usage.
                if update.content != expected.get(update.topic, ""):
                    metadata["status"] = "active"
                    metadata["updated_at"] = time.time()
                if update.content != expected.get(update.topic, ""):
                    atomic_write(self.topic_path(update.topic), update.content)
            self._save_state(state)
            self._write_index(state)

    def mark_processed(self, session_id: str, revision: str) -> None:
        with file_lock(self.lock_path(), blocking=True):
            state = self.read_state()
            state["processed"][session_id] = revision
            self._save_state(state)

    def set_pinned(self, topic: str, pinned: bool) -> None:
        check_topic(topic)
        with file_lock(self.lock_path(), blocking=True):
            state = self.read_state()
            self._register_topics(state)
            if topic not in state["topics"]:
                raise ConfigurationError("memory topic does not exist")
            state["topics"][topic]["pinned"] = pinned
            if pinned:
                state["topics"][topic]["status"] = "active"
            self._save_state(state)
            self._write_index(state)

    def forget(self, topic: str) -> None:
        check_topic(topic)
        with file_lock(self.lock_path(), blocking=True):
            state = self.read_state()
            state["forgotten"][topic] = time.time()
            state["topics"].pop(topic, None)
            # Save the tombstone first so an interrupted deletion cannot resurrect this topic.
            self._save_state(state)
            self.topic_path(topic).unlink(missing_ok=True)
            for path in self._resolve_inside(self.memory_dir / "candidates").glob("*.json"):
                path = self._resolve_inside(path)
                batch = json.loads(path.read_text(encoding="utf-8"))
                batch["memories"] = [m for m in batch["memories"] if m["topic"] != topic]
                atomic_write(path, json.dumps(batch, ensure_ascii=False, indent=2))
            self._write_index(state)

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


def _truncate_by_lines_and_bytes(
    content: str, *, max_lines: int, max_bytes: int
) -> tuple[str, bool]:
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
