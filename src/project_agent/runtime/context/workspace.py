from __future__ import annotations

from pathlib import Path

from project_agent.core.types import WorkspaceContext

KEY_PATHS = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", "pyproject.toml", "src", "tests")


class WorkspaceContextCollector:
    def __init__(self, *, max_top_level_entries: int = 20) -> None:
        self._max_top_level_entries = max_top_level_entries

    def collect(self, workspace_root: Path) -> WorkspaceContext:
        root = workspace_root.resolve()
        top_level_entries = self._collect_top_level_entries(root)
        key_paths = tuple(path for path in KEY_PATHS if (root / path).exists())
        return WorkspaceContext(
            root=root,
            top_level_entries=top_level_entries,
            key_paths=tuple(_display_path(path, root=root) for path in key_paths),
        )

    def _collect_top_level_entries(self, root: Path) -> tuple[str, ...]:
        try:
            entries = sorted(root.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            return ()
        return tuple(
            _display_path(path.name, root=root) for path in entries[: self._max_top_level_entries]
        )


def _display_path(path: str, *, root: Path) -> str:
    candidate = root / path
    return f"{path}/" if candidate.is_dir() else path
