from __future__ import annotations

from pathlib import Path

from project_agent.errors import ToolExecutionError


def resolve_workspace_path(*, workspace_root: Path, target_path: str) -> Path:
    root = workspace_root.resolve()
    candidate = (root / target_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ToolExecutionError(f"path escapes workspace: {target_path}") from error
    return candidate


def relative_workspace_path(*, workspace_root: Path, target_path: Path) -> str:
    return target_path.resolve().relative_to(workspace_root.resolve()).as_posix()
