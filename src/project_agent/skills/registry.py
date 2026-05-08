from __future__ import annotations

from project_agent.skills.models import Skill, SkillCatalogEntry


class SkillRegistry:
    def __init__(self, skills: tuple[Skill, ...]) -> None:
        skills_by_name: dict[str, Skill] = {}
        for skill in skills:
            name = skill.metadata.name
            if name in skills_by_name:
                raise ValueError(f"duplicate skill name: {name}")
            skills_by_name = {**skills_by_name, name: skill}
        self._skills = skills
        self._skills_by_name = skills_by_name

    @property
    def skills(self) -> tuple[Skill, ...]:
        return self._skills

    def get(self, name: str) -> Skill | None:
        return self._skills_by_name.get(name)

    def list_invocable(self) -> tuple[Skill, ...]:
        return tuple(skill for skill in self._skills if skill.metadata.user_invocable)

    def list_model_selectable(self) -> tuple[Skill, ...]:
        return tuple(skill for skill in self._skills if skill.metadata.model_selectable)

    def catalog_entries(self) -> tuple[SkillCatalogEntry, ...]:
        return tuple(
            SkillCatalogEntry(
                name=skill.metadata.name,
                description=skill.metadata.description,
                when_to_use=skill.metadata.when_to_use,
            )
            for skill in self.list_model_selectable()
        )
