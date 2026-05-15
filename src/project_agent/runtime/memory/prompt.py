from __future__ import annotations

from pathlib import Path

ENTRYPOINT_NAME = "MEMORY.md"


def build_memory_prompt(
    *,
    memory_dir: Path,
    entrypoint_content: str,
    entrypoint_truncated: bool,
    relevant_sections: tuple[str, ...] = (),
) -> str:
    lines = [
        "# Persistent Memory",
        "",
        f"You have a persistent, file-based memory system at `{memory_dir}`.",
        "",
        "## Storage model",
        f"- `{ENTRYPOINT_NAME}` is the memory index and should contain concise links or pointers.",
        "- Detailed memories should live in separate topic markdown files in the memory directory.",
        "- Keep each memory focused, durable, and easy to update or delete.",
        "",
        "## What to save",
        "- Long-lived user or project preferences that should affect future sessions.",
        "- Cross-session decisions, constraints, and non-obvious project context.",
        "- External reference locations and why they matter.",
        "",
        "## What not to save",
        "- Secrets, credentials, tokens, or private keys.",     
        "- Facts that are directly derivable from the current code or git history.",
        "- Temporary task state, one-off debugging notes, large logs, or raw tool output.",
        "- Duplicate, stale, or speculative information.",
        "",
        "## How to save",
        "1. Create or update a focused topic markdown file in the memory directory.",
        f"2. Add or update one concise index line in `{ENTRYPOINT_NAME}` pointing to that file.",
        "3. Update or remove stale memories rather than adding duplicates.",
        "",
        f"## {ENTRYPOINT_NAME} format",
        "Use structured index with links and brief descriptions:",
        "",
        "```markdown",
        "- [Context management](context_management.md) — Context module storage patterns",
        "- [Memory system](memory_system.md) — Persistent storage design",
        "- [Project preferences](preferences.md) — Build tools, coding style",
        "```",
        "",
        f"## Current {ENTRYPOINT_NAME} content",
        "",
    ]
    if entrypoint_content.strip():
        lines.append(entrypoint_content)
        if entrypoint_truncated:
            lines.append("")
            lines.append("[Memory index truncated]")
    else:
        lines.append(f"Your {ENTRYPOINT_NAME} is currently empty.")
    if relevant_sections:
        lines.extend(["", "## Relevant recalled memories", ""])
        lines.extend(relevant_sections)
    return "\n".join(lines)
