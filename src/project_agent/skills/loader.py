from __future__ import annotations

from pathlib import Path

from project_agent.skills.errors import SkillError
from project_agent.skills.models import Skill
from project_agent.skills.parser import parse_skill_markdown


def load_skills(
    *,
    builtin_root: Path | None,
    user_root: Path | None,
    project_root: Path | None,
) -> tuple[Skill, ...]:
    skills_by_name: dict[str, Skill] = {}
    for source, root in (
        ("builtin", builtin_root),
        ("user", user_root),
        ("project", project_root),
    ):
        if root is None:
            continue
        loaded = _load_skills_from_root(root=root, source=source)
        for skill in loaded:
            skills_by_name = {**skills_by_name, skill.metadata.name: skill}
    return tuple(skills_by_name.values())


def _load_skills_from_root(*, root: Path, source: str) -> tuple[Skill, ...]:
    if not root.exists():
        return ()
    if not root.is_dir():
        raise SkillError(f"skill root is not a directory: {root}")

    loaded_skills: dict[str, Skill] = {}
    for skill_dir in sorted(child for child in root.iterdir() if child.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        content = _read_skill_file(skill_file)
        metadata, body = parse_skill_markdown(content)
        if metadata.name in loaded_skills:
            raise SkillError(f"duplicate skill name in {source} skills: {metadata.name}")
        loaded_skills = {
            **loaded_skills,
            metadata.name: Skill(
                metadata=metadata,
                body=body,
                source=source,
                skill_dir=skill_dir,
                file_path=skill_file,
            ),
        }
    return tuple(loaded_skills.values())


def _read_skill_file(skill_file: Path) -> str:
    try:
        return skill_file.read_text(encoding="utf-8")
    except OSError as error:
        raise SkillError(f"failed to read skill file: {skill_file}") from error
