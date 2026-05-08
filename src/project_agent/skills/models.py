from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    when_to_use: str | None = None
    user_invocable: bool = True
    model_selectable: bool = True
    version: str | None = None
    shell_interpolation: bool = False


@dataclass(frozen=True)
class Skill:
    metadata: SkillMetadata
    body: str
    source: str
    skill_dir: Path
    file_path: Path


@dataclass(frozen=True)
class SkillCatalogEntry:
    name: str
    description: str
    when_to_use: str | None


@dataclass(frozen=True)
class SkillInvocation:
    skill_name: str
    raw_args: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class SkillRuntimeSettings:
    allow_command_substitution: bool
