from pathlib import Path

import pytest

from project_agent.skills.errors import SkillError
from project_agent.skills.loader import load_skills
from project_agent.skills.models import SkillRuntimeSettings
from project_agent.skills.preprocessor import SkillPromptPreprocessor, build_skill_invocation
from project_agent.skills.registry import SkillRegistry


def test_skill_preprocessor_expands_arguments_and_builtins(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "demo" / "SKILL.md",
        (
            "---\n"
            "name: demo\n"
            "description: demo skill\n"
            "---\n"
            "Skill={{skill_name}}\nArgs={{args}}\nFirst={{args[0]}}\n"
            "Dir={{skill_dir}}\nRoot={{workspace_root}}"
        ),
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    expanded = preprocessor.expand_invocation(
        build_skill_invocation(command_name="/demo", raw_args="hello world")
    )

    assert expanded.startswith("Skill: demo\n\n")
    assert "Skill=demo" in expanded
    assert "Args=hello world" in expanded
    assert "First=hello" in expanded
    assert f"Root={tmp_path.as_posix()}" in expanded


def test_skill_preprocessor_supports_skill_composition(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "child" / "SKILL.md",
        "---\nname: child\ndescription: child skill\n---\nChild {{args[0]}}",
    )
    _write_skill(
        project_root / "parent" / "SKILL.md",
        "---\nname: parent\ndescription: parent skill\n---\nBefore\n{{skill:child nested}}\nAfter",
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    expanded = preprocessor.expand_invocation(
        build_skill_invocation(command_name="/parent", raw_args="")
    )

    assert "Before\nChild nested\nAfter" in expanded


def test_skill_preprocessor_rejects_cycles(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "first" / "SKILL.md",
        "---\nname: first\ndescription: first skill\n---\n{{skill:second}}",
    )
    _write_skill(
        project_root / "second" / "SKILL.md",
        "---\nname: second\ndescription: second skill\n---\n{{skill:first}}",
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(SkillError, match="cycle"):
        preprocessor.expand_invocation(build_skill_invocation(command_name="/first", raw_args=""))


def test_skill_preprocessor_rejects_missing_positional_argument(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "needs-arg" / "SKILL.md",
        "---\nname: needs-arg\ndescription: arg skill\n---\nValue {{args[1]}}",
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(registry=registry, workspace_root=tmp_path)

    with pytest.raises(SkillError, match="missing required argument"):
        preprocessor.expand_invocation(
            build_skill_invocation(command_name="/needs-arg", raw_args="only-one")
        )


def test_skill_preprocessor_enforces_expansion_limit(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "big" / "SKILL.md",
        "---\nname: big\ndescription: big skill\n---\n1234567890",
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(
        registry=registry,
        workspace_root=tmp_path,
        max_expansion_chars=5,
    )

    with pytest.raises(SkillError, match="size limit"):
        preprocessor.expand_invocation(build_skill_invocation(command_name="/big", raw_args=""))


def test_skill_preprocessor_enforces_max_composition_depth(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "level-3" / "SKILL.md",
        "---\nname: level-3\ndescription: level 3\n---\nFinal",
    )
    _write_skill(
        project_root / "level-2" / "SKILL.md",
        "---\nname: level-2\ndescription: level 2\n---\n{{skill:level-3}}",
    )
    _write_skill(
        project_root / "level-1" / "SKILL.md",
        "---\nname: level-1\ndescription: level 1\n---\n{{skill:level-2}}",
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(
        registry=registry,
        workspace_root=tmp_path,
        max_composition_depth=2,
    )

    with pytest.raises(SkillError, match="depth exceeded"):
        preprocessor.expand_invocation(build_skill_invocation(command_name="/level-1", raw_args=""))


def test_skill_preprocessor_rejects_disabled_command_substitution(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "command" / "SKILL.md",
        (
            "---\n"
            "name: command\n"
            "description: command skill\n"
            "shell_interpolation: true\n"
            "---\n"
            "!`git status --short`"
        ),
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(
        registry=registry,
        workspace_root=tmp_path,
        allow_command_substitution=False,
    )

    with pytest.raises(SkillError, match="disabled by configuration"):
        preprocessor.expand_invocation(build_skill_invocation(command_name="/command", raw_args=""))


def test_skill_preprocessor_rejects_crlf_block_command_substitution(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "command" / "SKILL.md",
        (
            "---\r\n"
            "name: command\r\n"
            "description: command skill\r\n"
            "shell_interpolation: true\r\n"
            "---\r\n"
            "```!\r\n"
            "git status --short\r\n"
            "```"
        ),
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(
        registry=registry,
        workspace_root=tmp_path,
        allow_command_substitution=False,
    )

    with pytest.raises(SkillError, match="disabled by configuration"):
        preprocessor.expand_invocation(build_skill_invocation(command_name="/command", raw_args=""))


def test_skill_preprocessor_rejects_command_substitution_without_frontmatter_opt_in(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_skill(
        project_root / "command" / "SKILL.md",
        "---\nname: command\ndescription: command skill\n---\n!`git status --short`",
    )
    registry = SkillRegistry(
        load_skills(builtin_root=None, user_root=None, project_root=project_root)
    )
    preprocessor = _make_preprocessor(
        registry=registry,
        workspace_root=tmp_path,
        allow_command_substitution=True,
    )

    with pytest.raises(SkillError, match="shell_interpolation is false"):
        preprocessor.expand_invocation(build_skill_invocation(command_name="/command", raw_args=""))


def _make_preprocessor(
    *,
    registry: SkillRegistry,
    workspace_root: Path,
    max_composition_depth: int = 3,
    max_expansion_chars: int = 1000,
    allow_command_substitution: bool = False,
) -> SkillPromptPreprocessor:
    return SkillPromptPreprocessor(
        registry=registry,
        workspace_root=workspace_root,
        max_composition_depth=max_composition_depth,
        max_expansion_chars=max_expansion_chars,
        runtime_settings=SkillRuntimeSettings(
            allow_command_substitution=allow_command_substitution
        ),
    )


def _write_skill(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
