from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.runtime.context import relevance
from project_agent.runtime.context.relevance import RelevantFileCollector


def test_relevant_file_collector_matches_prompt_tokens_in_paths_and_content(tmp_path: Path) -> None:
    src_dir = tmp_path / "src" / "project_agent"
    tests_dir = tmp_path / "tests" / "unit"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (src_dir / "agent.py").write_text("class AgentRuntime:\n    pass\n", encoding="utf-8")
    (tests_dir / "test_runtime_agent.py").write_text(
        "def test_agent_runtime():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("runtime docs", encoding="utf-8")

    excerpts = RelevantFileCollector(
        max_relevant_files=2,
        max_relevant_file_chars=100,
    ).collect(
        workspace_root=tmp_path,
        user_input="change AgentRuntime behavior",
        recent_user_messages=(),
    )

    assert tuple(excerpt.path for excerpt in excerpts) == (
        "src/project_agent/agent.py",
        "tests/unit/test_runtime_agent.py",
    )
    assert "path token" in excerpts[0].reason or "content token" in excerpts[0].reason


def test_relevant_file_collector_uses_recent_user_messages_and_truncates(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.py").write_text("x" * 20 + " setting_token", encoding="utf-8")

    excerpts = RelevantFileCollector(
        max_relevant_files=1,
        max_relevant_file_chars=5,
    ).collect(
        workspace_root=tmp_path,
        user_input="continue",
        recent_user_messages=("update setting_token",),
    )

    assert len(excerpts) == 1
    assert excerpts[0].path == "src/config.py"
    assert excerpts[0].excerpt == "xxxxx"
    assert excerpts[0].truncated is True


def test_relevant_file_collector_limits_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for index in range(3):
        (src_dir / f"agent_{index}.py").write_text("agent", encoding="utf-8")

    monkeypatch.setattr(relevance, "MAX_CANDIDATE_FILES", 2)

    excerpts = RelevantFileCollector(
        max_relevant_files=10,
        max_relevant_file_chars=100,
    ).collect(
        workspace_root=tmp_path,
        user_input="agent",
        recent_user_messages=(),
    )

    assert tuple(excerpt.path for excerpt in excerpts) == ("src/agent_0.py", "src/agent_1.py")


def test_relevant_file_collector_reads_only_scan_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.py").write_text("x" * 5 + " setting_token", encoding="utf-8")

    monkeypatch.setattr(relevance, "MAX_FILE_SCAN_CHARS", 5)

    excerpts = RelevantFileCollector(
        max_relevant_files=1,
        max_relevant_file_chars=100,
    ).collect(
        workspace_root=tmp_path,
        user_input="setting_token",
        recent_user_messages=(),
    )

    assert excerpts == ()


def test_relevant_file_collector_returns_empty_tuple_without_matches(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    excerpts = RelevantFileCollector(
        max_relevant_files=3,
        max_relevant_file_chars=100,
    ).collect(
        workspace_root=tmp_path,
        user_input="unrelated_token",
        recent_user_messages=(),
    )

    assert excerpts == ()
