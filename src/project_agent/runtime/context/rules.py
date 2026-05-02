from __future__ import annotations

from pathlib import Path

from project_agent.core.types import RuleDocument

RULE_PATHS = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")


class RuleLoader:
    def __init__(self, *, max_rule_file_chars: int) -> None:
        self._max_rule_file_chars = max_rule_file_chars

    def load(self, workspace_root: Path) -> tuple[RuleDocument, ...]:
        root = workspace_root.resolve()
        rules: tuple[RuleDocument, ...] = ()
        for relative_path in RULE_PATHS:
            rule_path = root / relative_path
            if not rule_path.is_file() or not _is_within_workspace(root=root, path=rule_path):
                continue
            try:
                content = rule_path.read_text(encoding="utf-8")
            except OSError:
                continue
            truncated = len(content) > self._max_rule_file_chars
            rules = rules + (
                RuleDocument(
                    path=relative_path,
                    content=content[: self._max_rule_file_chars],
                    truncated=truncated,
                ),
            )
        return rules


def _is_within_workspace(*, root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True
