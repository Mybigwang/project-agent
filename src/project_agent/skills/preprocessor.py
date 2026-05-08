from __future__ import annotations

import re
import shlex
from pathlib import Path

from project_agent.skills.errors import SkillError
from project_agent.skills.models import Skill, SkillInvocation, SkillRuntimeSettings
from project_agent.skills.registry import SkillRegistry

SKILL_REFERENCE_PATTERN = re.compile(r"\{\{skill:(?P<reference>[^}]+)\}\}")
POSITIONAL_ARGUMENT_PATTERN = re.compile(r"\{\{args\[(?P<index>\d+)\]\}\}")
INLINE_COMMAND_PATTERN = re.compile(r"!`(?P<command>[^`]+)`")
BLOCK_COMMAND_PATTERN = re.compile(r"```!\r?\n(?P<command>[\s\S]*?)\r?\n```")


class SkillPromptPreprocessor:
    def __init__(
        self,
        *,
        registry: SkillRegistry,
        workspace_root: Path,
        max_composition_depth: int,
        max_expansion_chars: int,
        runtime_settings: SkillRuntimeSettings,
    ) -> None:
        self._registry = registry
        self._workspace_root = workspace_root
        self._max_composition_depth = max_composition_depth
        self._max_expansion_chars = max_expansion_chars
        self._runtime_settings = runtime_settings

    def expand_invocation(self, invocation: SkillInvocation) -> str:
        skill = self._require_skill(invocation.skill_name)
        expanded = self._expand_skill(
            skill=skill,
            invocation=invocation,
            depth=0,
            active_stack=(skill.metadata.name,),
        )
        return f"Skill: {skill.metadata.name}\n\n{expanded}"

    def _expand_skill(
        self,
        *,
        skill: Skill,
        invocation: SkillInvocation,
        depth: int,
        active_stack: tuple[str, ...],
    ) -> str:
        content = _replace_argument_placeholders(skill.body, invocation)
        content = _replace_builtin_placeholders(
            content=content,
            invocation=invocation,
            skill=skill,
            workspace_root=self._workspace_root,
        )
        content = self._replace_skill_references(
            content=content,
            depth=depth,
            active_stack=active_stack,
        )
        content = self._validate_command_substitution(content=content, skill=skill)
        if len(content) > self._max_expansion_chars:
            raise SkillError("skill expansion exceeds configured size limit")
        return content

    def _replace_skill_references(
        self,
        *,
        content: str,
        depth: int,
        active_stack: tuple[str, ...],
    ) -> str:
        def replace_match(match: re.Match[str]) -> str:
            raw_reference = match.group("reference").strip()
            if not raw_reference:
                raise SkillError("skill reference must not be empty")
            parts = shlex.split(raw_reference)
            if not parts:
                raise SkillError("skill reference must not be empty")
            if depth + 1 >= self._max_composition_depth:
                raise SkillError("skill composition depth exceeded")
            skill_name = parts[0]
            if skill_name in active_stack:
                cycle = " -> ".join((*active_stack, skill_name))
                raise SkillError(f"skill reference cycle detected: {cycle}")
            child_skill = self._require_skill(skill_name)
            child_invocation = SkillInvocation(
                skill_name=skill_name,
                raw_args=" ".join(parts[1:]),
                argv=tuple(parts[1:]),
            )
            return self._expand_skill(
                skill=child_skill,
                invocation=child_invocation,
                depth=depth + 1,
                active_stack=(*active_stack, skill_name),
            )

        return SKILL_REFERENCE_PATTERN.sub(replace_match, content)

    def _require_skill(self, skill_name: str) -> Skill:
        skill = self._registry.get(skill_name)
        if skill is None:
            raise SkillError(f"unknown skill: {skill_name}")
        return skill

    def _validate_command_substitution(self, *, content: str, skill: Skill) -> str:
        has_commands = bool(
            INLINE_COMMAND_PATTERN.search(content)
            or BLOCK_COMMAND_PATTERN.search(content)
        )
        if not has_commands:
            return content
        if not skill.metadata.shell_interpolation:
            raise SkillError(
                "skill "
                f"'{skill.metadata.name}' contains command substitution "
                "but shell_interpolation is false"
            )
        if not self._runtime_settings.allow_command_substitution:
            raise SkillError("skill command substitution is disabled by configuration")
        raise SkillError("skill command substitution is not implemented yet")


def build_skill_invocation(*, command_name: str, raw_args: str) -> SkillInvocation:
    try:
        argv = tuple(shlex.split(raw_args))
    except ValueError as error:
        raise SkillError(f"invalid skill arguments: {error}") from error
    return SkillInvocation(
        skill_name=command_name.removeprefix("/"),
        raw_args=raw_args.strip(),
        argv=argv,
    )


def _replace_argument_placeholders(content: str, invocation: SkillInvocation) -> str:
    expanded = content.replace("{{args}}", invocation.raw_args)

    def replace_match(match: re.Match[str]) -> str:
        index = int(match.group("index"))
        if index >= len(invocation.argv):
            raise SkillError(
                f"skill '{invocation.skill_name}' is missing required argument at position {index}"
            )
        return invocation.argv[index]

    return POSITIONAL_ARGUMENT_PATTERN.sub(replace_match, expanded)


def _replace_builtin_placeholders(
    *,
    content: str,
    invocation: SkillInvocation,
    skill: Skill,
    workspace_root: Path,
) -> str:
    replacements = {
        "{{skill_name}}": invocation.skill_name,
        "{{skill_dir}}": skill.skill_dir.as_posix(),
        "{{workspace_root}}": workspace_root.as_posix(),
    }
    expanded = content
    for old, new in replacements.items():
        expanded = expanded.replace(old, new)
    return expanded
