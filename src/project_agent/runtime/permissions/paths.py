from __future__ import annotations

from pathlib import Path

from project_agent.runtime.workspace import relative_workspace_path, resolve_workspace_path

PROTECTED_PATH_PREFIXES = (".git", ".project_agent", ".claude")


def resolve_permission_path(*, workspace_root: Path, raw_path: str) -> Path:
    return resolve_workspace_path(workspace_root=workspace_root, target_path=raw_path)


def relative_permission_path(*, workspace_root: Path, path: Path) -> str:
    return relative_workspace_path(workspace_root=workspace_root, target_path=path).replace("\\", "/")


def is_protected_path(*, workspace_root: Path, path: Path) -> bool:
    relative_path = relative_permission_path(workspace_root=workspace_root, path=path)
    return any(
        relative_path == prefix or relative_path.startswith(f"{prefix}/")
        for prefix in PROTECTED_PATH_PREFIXES
    )


def resolve_argument_paths(
    *, workspace_root: Path, arguments: dict[str, object], path_keys: tuple[str, ...] = ("path",)
) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    for key in path_keys:
        value = arguments.get(key)
        if isinstance(value, str) and value:
            resolved_paths.append(resolve_permission_path(workspace_root=workspace_root, raw_path=value))
    return tuple(resolved_paths)
