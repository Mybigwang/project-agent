from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from project_agent.core.types import (
    GitContext,
    Message,
    RelevantFileExcerpt,
    RepositoryContext,
    RuleDocument,
    WorkspaceContext,
)
from project_agent.runtime.context.git import GitContextCollector
from project_agent.runtime.context.relevance import RelevantFileCollector
from project_agent.runtime.context.rules import RuleLoader
from project_agent.runtime.context.workspace import WorkspaceContextCollector

SECRET_VALUE = "[REDACTED]"
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(['\"]?)(api[_-]?key|secret|token|password|passwd|pwd)(\1)"
    r"(\s*[:=]\s*)"
    r"([^\s'\"`,;}]+|['\"][^'\"]*['\"])",
)
ENV_SECRET_PATTERN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD)[A-Z0-9_]*)"
    r"="
    r"([^\s'\"`,;}]+|['\"][^'\"]*['\"])",
)


class RepositoryContextBuilder:
    def __init__(
        self,
        *,
        max_repository_context_chars: int,
        max_git_diff_chars: int,
        max_rule_file_chars: int,
        max_relevant_files: int,
        max_relevant_file_chars: int,
        recent_commits_count: int,
        context_command_timeout_seconds: float,
    ) -> None:
        self.max_repository_context_chars = max_repository_context_chars
        self.max_git_diff_chars = max_git_diff_chars
        self.max_rule_file_chars = max_rule_file_chars
        self.max_relevant_files = max_relevant_files
        self.max_relevant_file_chars = max_relevant_file_chars
        self.recent_commits_count = recent_commits_count
        self.context_command_timeout_seconds = context_command_timeout_seconds
        self._workspace_collector = WorkspaceContextCollector()
        self._git_collector = GitContextCollector(
            timeout_seconds=context_command_timeout_seconds,
            max_diff_chars=max_git_diff_chars,
            recent_commits_count=recent_commits_count,
        )
        self._rule_loader = RuleLoader(max_rule_file_chars=max_rule_file_chars)
        self._relevant_file_collector = RelevantFileCollector(
            max_relevant_files=max_relevant_files,
            max_relevant_file_chars=max_relevant_file_chars,
        )
        self._assembler = RepositoryContextAssembler(
            max_repository_context_chars=max_repository_context_chars
        )

    def build(
        self,
        *,
        workspace_root: Path,
        user_input: str,
        history: Sequence[Message],
    ) -> RepositoryContext:
        recent_user_messages = tuple(
            message.content for message in history if message.role == "user"
        )[-3:]
        workspace = self._workspace_collector.collect(workspace_root)
        git = self._git_collector.collect(workspace_root)
        rules = self._rule_loader.load(workspace_root)
        relevant_files = self._relevant_file_collector.collect(
            workspace_root=workspace_root,
            user_input=user_input,
            recent_user_messages=recent_user_messages,
        )
        return self._assembler.assemble(
            workspace=workspace,
            git=git,
            rules=rules,
            relevant_files=relevant_files,
        )


class RepositoryContextAssembler:
    def __init__(self, *, max_repository_context_chars: int) -> None:
        self.max_repository_context_chars = max_repository_context_chars

    def assemble(
        self,
        *,
        workspace: WorkspaceContext | None,
        git: GitContext | None,
        rules: tuple[RuleDocument, ...],
        relevant_files: tuple[RelevantFileExcerpt, ...],
    ) -> RepositoryContext:
        rendered = self._render(
            workspace=workspace,
            git=git,
            rules=rules,
            relevant_files=relevant_files,
            include_relevant=True,
            include_workspace=True,
        )
        if len(rendered) > self.max_repository_context_chars:
            rendered = self._render(
                workspace=workspace,
                git=git,
                rules=rules,
                relevant_files=(),
                include_relevant=False,
                include_workspace=False,
            )
        if len(rendered) > self.max_repository_context_chars:
            rendered = rendered[: self.max_repository_context_chars]
        return RepositoryContext(
            rendered=rendered,
            workspace=workspace,
            git=git,
            rules=rules,
            relevant_files=relevant_files,
        )

    def _render(
        self,
        *,
        workspace: WorkspaceContext | None,
        git: GitContext | None,
        rules: tuple[RuleDocument, ...],
        relevant_files: tuple[RelevantFileExcerpt, ...],
        include_relevant: bool,
        include_workspace: bool,
    ) -> str:
        sections: tuple[str, ...] = ("Repository context",)
        if rules:
            sections = sections + (_render_rules(rules),)
        if git is not None:
            sections = sections + (_render_git(git),)
        if include_relevant and relevant_files:
            sections = sections + (_render_relevant_files(relevant_files),)
        if include_workspace and workspace is not None:
            sections = sections + (_render_workspace(workspace),)
        return _redact_sensitive_text("\n\n".join(section for section in sections if section))


def _render_rules(rules: tuple[RuleDocument, ...]) -> str:
    lines: list[str] = ["Project rules"]
    for rule in rules:
        suffix = " (truncated)" if rule.truncated else ""
        lines.extend((f"- {rule.path}{suffix}", rule.content))
    return "\n".join(lines)


def _render_git(git: GitContext) -> str:
    lines: list[str] = ["Git context"]
    if not git.is_available:
        lines.append(f"- unavailable: {git.error or 'unknown error'}")
        return "\n".join(lines)
    if git.branch is not None:
        lines.append(f"- branch: {git.branch}")
    if git.status:
        lines.extend(("- status:", git.status))
    if git.diff:
        lines.extend(("- diff:", git.diff))
    if git.recent_commits:
        lines.append("- recent commits:")
        lines.extend(f"  {commit}" for commit in git.recent_commits)
    return "\n".join(lines)


def _render_relevant_files(relevant_files: tuple[RelevantFileExcerpt, ...]) -> str:
    lines: list[str] = ["Relevant files"]
    for file in relevant_files:
        suffix = " (truncated)" if file.truncated else ""
        lines.extend((f"- {file.path}{suffix}: {file.reason}", file.excerpt))
    return "\n".join(lines)


def _render_workspace(workspace: WorkspaceContext) -> str:
    lines: list[str] = ["Workspace overview", f"- root: {workspace.root}"]
    if workspace.top_level_entries:
        lines.append(f"- top level: {', '.join(workspace.top_level_entries)}")
    if workspace.key_paths:
        lines.append(f"- key paths: {', '.join(workspace.key_paths)}")
    return "\n".join(lines)


def _redact_sensitive_text(text: str) -> str:
    redacted = SECRET_ASSIGNMENT_PATTERN.sub(_redact_assignment, text)
    return ENV_SECRET_PATTERN.sub(_redact_env_assignment, redacted)


def _redact_assignment(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}{SECRET_VALUE}"


def _redact_env_assignment(match: re.Match[str]) -> str:
    return f"{match.group(1)}={SECRET_VALUE}"
