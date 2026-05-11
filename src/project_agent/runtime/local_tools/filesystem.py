from __future__ import annotations

from pathlib import Path

from project_agent.core.types import ToolResult
from project_agent.runtime.permissions.types import ToolPermissionCategory
from project_agent.errors import ToolExecutionError
from project_agent.runtime.workspace import relative_workspace_path, resolve_workspace_path


class ReadFileTool:
    name = "read_file"
    description = "Read a file from the workspace"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    }
    is_read_only = True
    permission_category = ToolPermissionCategory.READ

    def __init__(self, *, max_chars: int) -> None:
        self._max_chars = max_chars

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        path_argument = arguments.get("path")
        start_line = arguments.get("start_line")
        end_line = arguments.get("end_line")
        if not isinstance(path_argument, str) or not path_argument:
            return ToolResult(
                name=self.name,
                content="invalid path",
                is_error=True,
                error_code="invalid_arguments",
            )
        if start_line is not None and (not isinstance(start_line, int) or start_line < 1):
            return ToolResult(
                name=self.name,
                content="start_line must be >= 1",
                is_error=True,
                error_code="invalid_arguments",
            )
        if end_line is not None and (not isinstance(end_line, int) or end_line < 1):
            return ToolResult(
                name=self.name,
                content="end_line must be >= 1",
                is_error=True,
                error_code="invalid_arguments",
            )
        if start_line is not None and end_line is not None and start_line > end_line:
            return ToolResult(
                name=self.name,
                content="start_line must be <= end_line",
                is_error=True,
                error_code="invalid_arguments",
            )

        try:
            file_path = resolve_workspace_path(
                workspace_root=workspace_root, target_path=path_argument
            )
            text = file_path.read_text(encoding="utf-8")
        except ToolExecutionError:
            return ToolResult(
                name=self.name,
                content=f"path escapes workspace: {path_argument}",
                is_error=True,
                error_code="workspace_boundary_violation",
            )
        except OSError as error:
            return ToolResult(
                name=self.name,
                content=f"failed to read file: {error}",
                is_error=True,
                error_code="file_read_failed",
                retryable=True,
            )

        selected_text = self._select_lines(text=text, start_line=start_line, end_line=end_line)
        truncated = len(selected_text) > self._max_chars
        content = selected_text[: self._max_chars]
        return ToolResult(
            name=self.name,
            content=content,
            data={
                "path": relative_workspace_path(
                    workspace_root=workspace_root, target_path=file_path
                ),
                "start_line": start_line,
                "end_line": end_line,
                "truncated": truncated,
            },
        )

    def _select_lines(self, *, text: str, start_line: int | None, end_line: int | None) -> str:
        if start_line is None and end_line is None:
            return text

        lines = text.splitlines(keepends=True)
        start_index = 0 if start_line is None else start_line - 1
        end_index = len(lines) if end_line is None else end_line
        return "".join(lines[start_index:end_index])


class WriteFileTool:
    name = "write_file"
    description = "Write a file in the workspace"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        path_argument = arguments.get("path")
        content_argument = arguments.get("content")
        if not isinstance(path_argument, str) or not isinstance(content_argument, str):
            return ToolResult(
                name=self.name,
                content="invalid arguments",
                is_error=True,
                error_code="invalid_arguments",
            )

        try:
            file_path = resolve_workspace_path(
                workspace_root=workspace_root, target_path=path_argument
            )
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content_argument, encoding="utf-8")
        except ToolExecutionError:
            return ToolResult(
                name=self.name,
                content=f"path escapes workspace: {path_argument}",
                is_error=True,
                error_code="workspace_boundary_violation",
            )
        except OSError as error:
            return ToolResult(
                name=self.name,
                content=f"failed to write file: {error}",
                is_error=True,
                error_code="file_write_failed",
            )

        return ToolResult(
            name=self.name,
            content=f"wrote file: {path_argument}",
            data={
                "path": relative_workspace_path(
                    workspace_root=workspace_root, target_path=file_path
                ),
                "bytes_written": len(content_argument.encode("utf-8")),
            },
        )


class EditFileTool:
    name = "edit_file"
    description = "Edit a file in the workspace"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "old_text", "new_text"],
    }
    is_read_only = False
    permission_category = ToolPermissionCategory.WRITE

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        path_argument = arguments.get("path")
        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        replace_all = arguments.get("replace_all", False)
        if (
            not isinstance(path_argument, str)
            or not isinstance(old_text, str)
            or not isinstance(new_text, str)
        ):
            return ToolResult(
                name=self.name,
                content="invalid arguments",
                is_error=True,
                error_code="invalid_arguments",
            )
        if not isinstance(replace_all, bool):
            return ToolResult(
                name=self.name,
                content="replace_all must be a boolean",
                is_error=True,
                error_code="invalid_arguments",
            )

        try:
            file_path = resolve_workspace_path(
                workspace_root=workspace_root, target_path=path_argument
            )
            original = file_path.read_text(encoding="utf-8")
        except ToolExecutionError:
            return ToolResult(
                name=self.name,
                content=f"path escapes workspace: {path_argument}",
                is_error=True,
                error_code="workspace_boundary_violation",
            )
        except OSError as error:
            return ToolResult(
                name=self.name,
                content=f"failed to edit file: {error}",
                is_error=True,
                error_code="file_edit_failed",
            )

        matches = original.count(old_text)
        if matches == 0:
            return ToolResult(
                name=self.name,
                content="old_text not found",
                is_error=True,
                error_code="edit_not_found",
            )
        if matches > 1 and not replace_all:
            return ToolResult(
                name=self.name,
                content="old_text is not unique",
                is_error=True,
                error_code="edit_not_unique",
            )

        updated = (
            original.replace(old_text, new_text)
            if replace_all
            else original.replace(old_text, new_text, 1)
        )
        try:
            file_path.write_text(updated, encoding="utf-8")
        except OSError as error:
            return ToolResult(
                name=self.name,
                content=f"failed to edit file: {error}",
                is_error=True,
                error_code="file_edit_failed",
            )

        replacements = matches if replace_all else 1
        return ToolResult(
            name=self.name,
            content=f"edited file: {path_argument}",
            data={
                "path": relative_workspace_path(
                    workspace_root=workspace_root, target_path=file_path
                ),
                "replacements": replacements,
            },
        )


class ListFilesTool:
    name = "list_files"
    description = "List files in the workspace"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "glob": {"type": "string"},
        },
    }
    is_read_only = True
    permission_category = ToolPermissionCategory.READ

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        path_argument = arguments.get("path", ".")
        glob_pattern = arguments.get("glob", "**/*")
        if not isinstance(path_argument, str) or not isinstance(glob_pattern, str):
            return ToolResult(
                name=self.name,
                content="invalid arguments",
                is_error=True,
                error_code="invalid_arguments",
            )

        try:
            search_root = resolve_workspace_path(
                workspace_root=workspace_root, target_path=path_argument
            )
        except ToolExecutionError:
            return ToolResult(
                name=self.name,
                content=f"path escapes workspace: {path_argument}",
                is_error=True,
                error_code="workspace_boundary_violation",
            )

        paths = tuple(
            relative_workspace_path(workspace_root=workspace_root, target_path=path)
            for path in sorted(search_root.glob(glob_pattern))
            if path.is_file() and _is_within_workspace(workspace_root=workspace_root, path=path)
        )
        return ToolResult(name=self.name, content="listed files", data={"paths": list(paths)})


def _is_within_workspace(*, workspace_root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return False
    return True
