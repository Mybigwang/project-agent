from pathlib import Path

from project_agent.runtime.memory.prompt import build_memory_prompt


def test_memory_prompt_includes_guidance_and_entrypoint(tmp_path: Path) -> None:
    prompt = build_memory_prompt(
        memory_dir=tmp_path,
        entrypoint_content="- [Auth](auth.md) — login decisions",
        entrypoint_truncated=False,
    )

    assert str(tmp_path) in prompt
    assert "file-based memory system" in prompt
    assert "What to save" in prompt
    assert "What not to save" in prompt
    assert "- [Auth](auth.md)" in prompt


def test_memory_prompt_marks_empty_entrypoint(tmp_path: Path) -> None:
    prompt = build_memory_prompt(
        memory_dir=tmp_path,
        entrypoint_content="",
        entrypoint_truncated=False,
    )

    assert "MEMORY.md is currently empty" in prompt


def test_memory_prompt_marks_truncated_entrypoint(tmp_path: Path) -> None:
    prompt = build_memory_prompt(
        memory_dir=tmp_path,
        entrypoint_content="content",
        entrypoint_truncated=True,
    )

    assert "[Memory index truncated]" in prompt


def test_memory_prompt_includes_relevant_sections(tmp_path: Path) -> None:
    prompt = build_memory_prompt(
        memory_dir=tmp_path,
        entrypoint_content="content",
        entrypoint_truncated=False,
        relevant_sections=("## Relevant memory: auth.md\n\ndetails",),
    )

    assert "Relevant recalled memories" in prompt
    assert "## Relevant memory: auth.md" in prompt
