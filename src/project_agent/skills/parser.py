from __future__ import annotations

import re

from project_agent.skills.errors import SkillError
from project_agent.skills.models import SkillMetadata

FRONTMATTER_PATTERN = re.compile(
    r"\A---\r?\n(?P<frontmatter>[\s\S]*?)\r?\n---\r?\n?(?P<body>[\s\S]*)\Z"
)

KEY_VALUE_PATTERN = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*)$")


def parse_skill_markdown(content: str) -> tuple[SkillMetadata, str]:
    match = FRONTMATTER_PATTERN.match(content)
    if match is None:
        raise SkillError("skill file must start with YAML frontmatter")
    frontmatter = match.group("frontmatter")
    body = match.group("body").strip()
    if not body:
        raise SkillError("skill body must not be empty")
    metadata = parse_skill_frontmatter(frontmatter)
    return metadata, body


def parse_skill_frontmatter(frontmatter: str) -> SkillMetadata:
    values: dict[str, object] = {}
    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = KEY_VALUE_PATTERN.match(line)
        if match is None:
            raise SkillError(f"invalid frontmatter line: {raw_line}")
        key = match.group("key")
        value = _parse_scalar(match.group("value"))
        values[key] = value

    name = values.get("name")
    description = values.get("description")
    when_to_use = values.get("when_to_use")
    user_invocable = values.get("user_invocable", True)
    model_selectable = values.get("model_selectable", True)
    version = values.get("version")
    shell_interpolation = values.get("shell_interpolation", False)

    if not isinstance(name, str) or not name.strip():
        raise SkillError("skill name must be a non-empty string")
    if name.startswith("/"):
        raise SkillError("skill name must not start with '/'")
    if not isinstance(description, str) or not description.strip():
        raise SkillError("skill description must be a non-empty string")
    if when_to_use is not None and not isinstance(when_to_use, str):
        raise SkillError("skill when_to_use must be a string")
    if not isinstance(user_invocable, bool):
        raise SkillError("skill user_invocable must be a boolean")
    if not isinstance(model_selectable, bool):
        raise SkillError("skill model_selectable must be a boolean")
    if version is not None and not isinstance(version, str):
        raise SkillError("skill version must be a string")
    if not isinstance(shell_interpolation, bool):
        raise SkillError("skill shell_interpolation must be a boolean")

    return SkillMetadata(
        name=name.strip(),
        description=description.strip(),
        when_to_use=when_to_use.strip() if isinstance(when_to_use, str) else None,
        user_invocable=user_invocable,
        model_selectable=model_selectable,
        version=version.strip() if isinstance(version, str) else None,
        shell_interpolation=shell_interpolation,
    )


def _parse_scalar(raw_value: str) -> object:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value
