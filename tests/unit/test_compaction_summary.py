from __future__ import annotations

from project_agent.core.types import ContextManagementState, Message, Task, TaskPlan
from project_agent.runtime.context_management.summary import CompactionSummaryBuilder


def test_compaction_summary_builder_produces_structured_snapshot() -> None:
    builder = CompactionSummaryBuilder(
        profile="compact-default",
        version="v1",
        max_summary_tokens=400,
    )

    snapshot = builder.build_summary(
        messages=(
            Message(role="user", content="Investigate runtime context bug"),
            Message(role="assistant", content="Found the affected modules"),
        ),
        task_plan=TaskPlan(tasks=(Task(id="1", title="Fix runtime", description="Fix"),)),
        existing_state=ContextManagementState(profile="compact-default", version="v1"),
    )

    assert snapshot.intent == "Investigate runtime context bug"
    assert snapshot.tasks == ("Fix runtime",)
    assert "Intent:" in snapshot.summary_text
    assert snapshot.source_message_count == 2
