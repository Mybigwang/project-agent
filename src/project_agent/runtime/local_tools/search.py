from __future__ import annotations

from pathlib import Path

from project_agent.core.types import ToolResult
from project_agent.errors import ToolExecutionError
from project_agent.runtime.workspace import relative_workspace_path, resolve_workspace_path


class SearchCodeTool:
    name = "search_code"
    description = "Search text in workspace files"
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "glob": {"type": "string"},
        },
        "required": ["pattern"],
    }
    is_read_only = True

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        pattern = arguments.get("pattern")
        path_argument = arguments.get("path", ".")
        glob_pattern = arguments.get("glob", "**/*")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult(
                name=self.name,
                content="invalid pattern",
                is_error=True,
                error_code="invalid_arguments",
            )
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

        matches: list[dict[str, object]] = []
        for file_path in sorted(search_root.glob(glob_pattern)):
            if not file_path.is_file() or not _is_within_workspace(
                workspace_root=workspace_root, path=file_path
            ):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except OSError as error:
                return ToolResult(
                    name=self.name,
                    content=f"failed to search file: {error}",
                    is_error=True,
                    error_code="search_failed",
                    retryable=True,
                )
            for line_number, line in enumerate(lines, start=1):
                if pattern in line:
                    matches.append(
                        {
                            "path": relative_workspace_path(
                                workspace_root=workspace_root, target_path=file_path
                            ),
                            "line": line_number,
                            "content": line,
                        }
                    )

        return ToolResult(
            name=self.name, content=f"found {len(matches)} matches", data={"matches": matches}
        )


def _is_within_workspace(*, workspace_root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return False
    return True
