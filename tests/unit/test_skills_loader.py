from pathlib import Path

import pytest

from project_agent.skills.errors import SkillError
from project_agent.skills.loader import load_skills


def test_load_skills_prefers_project_over_builtin(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin"
    project_root = tmp_path / "project"
    _write_skill(
        builtin_root / "explain-code" / "SKILL.md",
        "---\nname: explain-code\ndescription: builtin\n---\nBuiltin body",
    )
    _write_skill(
        project_root / "override" / "SKILL.md",
        "---\nname: explain-code\ndescription: project\n---\nProject body",
    )

    skills = load_skills(builtin_root=builtin_root, user_root=None, project_root=project_root)

    assert len(skills) == 1
    skill = skills[0]
    assert skill.metadata.name == "explain-code"
    assert skill.metadata.description == "project"
    assert skill.body == "Project body"
    assert skill.source == "project"


def test_load_skills_accepts_crlf_frontmatter(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "windows-skill" / "SKILL.md",
        "---\r\nname: windows-skill\r\ndescription: windows\r\n---\r\nCRLF body\r\n",
    )

    skills = load_skills(builtin_root=None, user_root=None, project_root=project_root)

    assert len(skills) == 1
    assert skills[0].metadata.name == "windows-skill"
    assert skills[0].body == "CRLF body"


def test_load_skills_rejects_duplicate_names_in_same_source(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "first" / "SKILL.md",
        "---\nname: duplicate\ndescription: first\n---\nFirst body",
    )
    _write_skill(
        project_root / "second" / "SKILL.md",
        "---\nname: duplicate\ndescription: second\n---\nSecond body",
    )

    with pytest.raises(SkillError, match="duplicate skill name"):
        load_skills(builtin_root=None, user_root=None, project_root=project_root)


def test_load_skills_ignores_directories_without_skill_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / "empty").mkdir(parents=True)

    skills = load_skills(builtin_root=None, user_root=None, project_root=project_root)

    assert skills == ()


def test_load_skills_rejects_invalid_frontmatter(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(project_root / "broken" / "SKILL.md", "not-frontmatter")

    with pytest.raises(SkillError, match="frontmatter"):
        load_skills(builtin_root=None, user_root=None, project_root=project_root)


def _write_skill(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
