from __future__ import annotations

from pathlib import Path

import pytest

from project_agent.runtime.local_tools.filesystem import (
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    WriteFileTool,
)
from project_agent.runtime.local_tools.search import SearchCodeTool


def test_read_file_returns_content_and_metadata(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.txt"
    file_path.write_text("line 1\nline 2\n", encoding="utf-8")

    result = ReadFileTool(max_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"path": "demo.txt"},
    )

    assert result.is_error is False
    assert result.content == "line 1\nline 2\n"
    assert result.data == {
        "path": "demo.txt",
        "start_line": None,
        "end_line": None,
        "truncated": False,
    }


def test_read_file_respects_start_line_and_end_line(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.txt"
    file_path.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

    result = ReadFileTool(max_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"path": "demo.txt", "start_line": 2, "end_line": 3},
    )

    assert result.is_error is False
    assert result.content == "line 2\nline 3\n"
    assert result.data == {
        "path": "demo.txt",
        "start_line": 2,
        "end_line": 3,
        "truncated": False,
    }


def test_read_file_rejects_invalid_line_range(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.txt"
    file_path.write_text("line 1\nline 2\n", encoding="utf-8")

    result = ReadFileTool(max_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"path": "demo.txt", "start_line": 3, "end_line": 2},
    )

    assert result.is_error is True
    assert result.error_code == "invalid_arguments"
    result = WriteFileTool().run(
        workspace_root=tmp_path,
        arguments={"path": "nested/demo.txt", "content": "hello"},
    )

    assert result.is_error is False
    assert (tmp_path / "nested" / "demo.txt").read_text(encoding="utf-8") == "hello"
    assert result.data == {"path": "nested/demo.txt", "bytes_written": 5}


def test_edit_file_replaces_exact_match(tmp_path: Path) -> None:
    path = tmp_path / "demo.txt"
    path.write_text("hello world", encoding="utf-8")

    result = EditFileTool().run(
        workspace_root=tmp_path,
        arguments={"path": "demo.txt", "old_text": "world", "new_text": "agent"},
    )

    assert result.is_error is False
    assert path.read_text(encoding="utf-8") == "hello agent"
    assert result.data == {"path": "demo.txt", "replacements": 1}


def test_edit_file_rejects_ambiguous_match_without_replace_all(tmp_path: Path) -> None:
    path = tmp_path / "demo.txt"
    path.write_text("a b a", encoding="utf-8")

    result = EditFileTool().run(
        workspace_root=tmp_path,
        arguments={"path": "demo.txt", "old_text": "a", "new_text": "z"},
    )

    assert result.is_error is True
    assert result.error_code == "edit_not_unique"


def test_list_files_returns_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.py").write_text("b", encoding="utf-8")

    result = ListFilesTool().run(workspace_root=tmp_path, arguments={})

    assert result.is_error is False
    assert result.data == {"paths": ["a.txt", "nested/b.py"]}


def test_search_code_returns_matching_lines(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("beta\ngamma\n", encoding="utf-8")

    result = SearchCodeTool().run(
        workspace_root=tmp_path,
        arguments={"pattern": "beta", "glob": "*.py"},
    )

    assert result.is_error is False
    assert result.data == {
        "matches": [
            {"path": "a.py", "line": 2, "content": "beta"},
            {"path": "b.py", "line": 1, "content": "beta"},
        ]
    }


def test_filesystem_tools_reject_workspace_escape(tmp_path: Path) -> None:
    result = ReadFileTool(max_chars=1000).run(
        workspace_root=tmp_path,
        arguments={"path": "../outside.txt"},
    )

    assert result.is_error is True
    assert result.error_code == "workspace_boundary_violation"


def test_list_files_skips_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_list.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    result = ListFilesTool().run(workspace_root=tmp_path, arguments={})

    assert result.is_error is False
    assert result.data == {"paths": []}


def test_search_code_skips_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_search.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    result = SearchCodeTool().run(
        workspace_root=tmp_path,
        arguments={"pattern": "secret", "glob": "*.txt"},
    )

    assert result.is_error is False
    assert result.data == {"matches": []}
