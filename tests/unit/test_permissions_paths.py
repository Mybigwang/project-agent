from pathlib import Path

import pytest

from project_agent.errors import ToolExecutionError
from project_agent.runtime.permissions.paths import is_protected_path, resolve_permission_path


def test_resolve_permission_path_stays_within_workspace(tmp_path: Path) -> None:
    resolved = resolve_permission_path(workspace_root=tmp_path, raw_path="src/main.py")

    assert resolved == (tmp_path / "src" / "main.py").resolve()


def test_resolve_permission_path_rejects_workspace_escape(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="escapes workspace"):
        resolve_permission_path(workspace_root=tmp_path, raw_path="../secret.txt")


@pytest.mark.parametrize(
    "relative_path",
    [".git/config", ".project_agent/skills/demo/SKILL.md", ".claude/settings.json"],
)
def test_is_protected_path_detects_protected_prefixes(tmp_path: Path, relative_path: str) -> None:
    path = (tmp_path / relative_path).resolve()

    assert is_protected_path(workspace_root=tmp_path, path=path) is True
