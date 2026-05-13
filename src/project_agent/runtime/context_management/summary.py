from __future__ import annotations

from collections.abc import Sequence

from project_agent.core.types import CompactionSummarySnapshot, ContextManagementState, Message, TaskPlan


class CompactionSummaryBuilder:
    def __init__(self, *, profile: str, version: str, max_summary_tokens: int) -> None:
        self.profile = profile
        self.version = version
        self.max_summary_tokens = max_summary_tokens

    def build_summary(
        self,
        *,
        messages: Sequence[Message],
        task_plan: TaskPlan | None,
        existing_state: ContextManagementState | None,
    ) -> CompactionSummarySnapshot:
        user_messages = tuple(message.content for message in messages if message.role == "user")
        assistant_messages = tuple(message.content for message in messages if message.role == "assistant" and message.content)
        tool_errors = tuple(message.content for message in messages if message.role == "tool" and '"status": "error"' in message.content)
        tasks = tuple(task.title for task in task_plan.tasks) if task_plan is not None else ()
        current_focus = None
        if task_plan is not None:
            for task in task_plan.tasks:
                if task.status in {"pending", "in_progress", "blocked"}:
                    current_focus = task.title
                    break
        intent = user_messages[-1] if user_messages else ""
        message_highlights = user_messages[-3:] + assistant_messages[-2:]
        kept_conclusions = assistant_messages[-3:]
        concepts = tuple(sorted({word for text in user_messages[-3:] for word in text.split()[:6]}))[:8]
        environment: tuple[str, ...] = ()
        if existing_state is not None and existing_state.latest_budget is not None:
            environment = (
                f"fill_ratio={existing_state.latest_budget.fill_ratio:.2f}",
                f"token_limit={existing_state.latest_budget.estimated_tokens_limit}",
            )
        files = ()
        summary_lines = [
            f"Intent: {intent or 'n/a'}",
            f"Concepts: {', '.join(concepts) or 'n/a'}",
            f"Files: {', '.join(files) or 'n/a'}",
            f"Errors: {' | '.join(tool_errors[-2:]) or 'n/a'}",
            f"Message Highlights: {' | '.join(message_highlights) or 'n/a'}",
            f"Tasks: {', '.join(tasks) or 'n/a'}",
            f"Current Focus: {current_focus or 'n/a'}",
            f"Environment / Constraints: {', '.join(environment) or 'n/a'}",
            f"Kept Conclusions: {' | '.join(kept_conclusions) or 'n/a'}",
        ]
        summary_text = "\n".join(summary_lines)
        max_summary_chars = max(1, self.max_summary_tokens * 4)
        if len(summary_text) > max_summary_chars:
            summary_text = summary_text[: max_summary_chars - 1] + "…"
        return CompactionSummarySnapshot(
            profile=self.profile,
            version=self.version,
            summary_text=summary_text,
            intent=intent,
            concepts=concepts,
            files=files,
            errors=tool_errors[-3:],
            message_highlights=message_highlights,
            tasks=tasks,
            current_focus=current_focus,
            environment=environment,
            kept_conclusions=kept_conclusions,
            source_message_count=len(messages),
        )
