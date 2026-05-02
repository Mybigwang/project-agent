from __future__ import annotations

from pathlib import Path

from project_agent.core.types import GitContext, RelevantFileExcerpt, RuleDocument, WorkspaceContext
from project_agent.runtime.context.assembler import RepositoryContextAssembler


def test_repository_context_assembler_renders_sections_in_priority_order(tmp_path: Path) -> None:
    context = RepositoryContextAssembler(max_repository_context_chars=10_000).assemble(
        workspace=WorkspaceContext(
            root=tmp_path,
            top_level_entries=("src/", "tests/"),
            key_paths=("CLAUDE.md",),
        ),
        git=GitContext(
            is_available=True,
            branch="main",
            status="## main\n M src/app.py",
            diff="+change",
            recent_commits=("abc123 init",),
            error=None,
        ),
        rules=(RuleDocument(path="CLAUDE.md", content="Use Mengqing", truncated=False),),
        relevant_files=(
            RelevantFileExcerpt(
                path="src/app.py",
                reason="content token: app",
                excerpt="print('hi')",
                truncated=False,
            ),
        ),
    )

    assert context.rendered.index("Project rules") < context.rendered.index("Git context")
    assert context.rendered.index("Git context") < context.rendered.index("Relevant files")
    assert context.rendered.index("Relevant files") < context.rendered.index("Workspace overview")
    assert context.rendered.startswith("Repository context")


def test_repository_context_assembler_redacts_sensitive_values(tmp_path: Path) -> None:
    context = RepositoryContextAssembler(max_repository_context_chars=10_000).assemble(
        workspace=None,
        git=GitContext(
            is_available=True,
            branch="main",
            status="",
            diff='+API_KEY=sk-live-secret\n+password: hunter2\n+"api_key": "json-secret"',
            recent_commits=(),
            error=None,
        ),
        rules=(RuleDocument(path="CLAUDE.md", content="token = abc123", truncated=False),),
        relevant_files=(
            RelevantFileExcerpt(
                path="src/app.py",
                reason="content token: secret",
                excerpt='secret="value"',
                truncated=False,
            ),
        ),
    )

    assert "sk-live-secret" not in context.rendered
    assert "hunter2" not in context.rendered
    assert "abc123" not in context.rendered
    assert "json-secret" not in context.rendered
    assert "value" not in context.rendered
    assert context.rendered.count("[REDACTED]") == 6


def test_repository_context_assembler_preserves_high_priority_content_when_trimming(
    tmp_path: Path,
) -> None:
    context = RepositoryContextAssembler(max_repository_context_chars=120).assemble(
        workspace=WorkspaceContext(
            root=tmp_path,
            top_level_entries=("low-priority-workspace-entry",),
            key_paths=(),
        ),
        git=GitContext(
            is_available=True,
            branch="main",
            status="git status should stay",
            diff="x" * 300,
            recent_commits=(),
            error=None,
        ),
        rules=(RuleDocument(path="CLAUDE.md", content="critical rule", truncated=False),),
        relevant_files=(
            RelevantFileExcerpt(
                path="src/app.py",
                reason="content token",
                excerpt="x" * 300,
                truncated=False,
            ),
        ),
    )

    assert len(context.rendered) <= 120
    assert "critical rule" in context.rendered
    assert "git status should stay" in context.rendered
    assert "low-priority-workspace-entry" not in context.rendered
