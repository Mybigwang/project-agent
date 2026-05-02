from __future__ import annotations

from pathlib import Path

from project_agent.runtime.context.workspace import WorkspaceContextCollector


def test_workspace_context_collector_collects_top_level_and_key_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "CLAUDE.md").write_text("rules", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
    (tmp_path / "z.txt").write_text("z", encoding="utf-8")

    context = WorkspaceContextCollector(max_top_level_entries=3).collect(tmp_path)

    assert context.root == tmp_path.resolve()
    assert context.top_level_entries == ("CLAUDE.md", "pyproject.toml", "src/")
    assert context.key_paths == ("CLAUDE.md", "pyproject.toml", "src/", "tests/")
