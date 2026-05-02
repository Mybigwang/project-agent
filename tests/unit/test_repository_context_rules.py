from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.runtime.context.rules import RuleLoader


def test_rule_loader_loads_known_rule_files_in_priority_order(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / "CLAUDE.md").write_text("root rules", encoding="utf-8")
    (tmp_path / ".claude" / "CLAUDE.md").write_text("nested rules", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("agent rules", encoding="utf-8")

    rules = RuleLoader(max_rule_file_chars=100).load(tmp_path)

    assert tuple(rule.path for rule in rules) == ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")
    assert tuple(rule.content for rule in rules) == ("root rules", "nested rules", "agent rules")
    assert all(not rule.truncated for rule in rules)


def test_rule_loader_truncates_rule_content(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("abcdef", encoding="utf-8")

    rules = RuleLoader(max_rule_file_chars=3).load(tmp_path)

    assert len(rules) == 1
    assert rules[0].content == "abc"
    assert rules[0].truncated is True


def test_rule_loader_skips_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_rules.md"
    outside.write_text("external rules", encoding="utf-8")
    link = tmp_path / "CLAUDE.md"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    assert RuleLoader(max_rule_file_chars=100).load(tmp_path) == ()
