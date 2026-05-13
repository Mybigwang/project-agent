from __future__ import annotations

from collections.abc import Sequence

from project_agent.core.types import (
    AutoCompactionState,
    BudgetSnapshot,
    CompactionSummarySnapshot,
    ContextManagementState,
    Message,
)
from project_agent.runtime.context_management.auto_compaction import AutoCompactionPolicy
from project_agent.runtime.context_management.manager import ContextManager
from project_agent.runtime.context_management.micro_compaction import MicroCompactor


class CountingBudgetEstimator:
    def estimate_messages(
        self,
        *,
        messages: Sequence[Message],
        token_limit: int,
        profile: str,
        version: str,
    ) -> BudgetSnapshot:
        used = len(messages)
        return BudgetSnapshot(
            estimated_tokens_used=used,
            estimated_tokens_limit=token_limit,
            fill_ratio=used / token_limit,
            profile=profile,
            version=version,
        )


class StaticSummaryBuilder:
    def __init__(self, summary_text: str = "Intent: compact") -> None:
        self.summary_text = summary_text

    def build_summary(
        self,
        *,
        messages: Sequence[Message],
        task_plan: object | None,
        existing_state: ContextManagementState | None,
    ) -> CompactionSummarySnapshot:
        del task_plan, existing_state
        return CompactionSummarySnapshot(
            profile="compact-default",
            version="v1",
            summary_text=self.summary_text,
            intent=messages[-1].content if messages else "",
        )


def _message(index: int) -> Message:
    return Message(role="user", content=f"message-{index}")


def test_context_manager_auto_compaction_trims_messages_when_budget_exceeded() -> None:
    manager = ContextManager(
        budget_estimator=CountingBudgetEstimator(),
        micro_compactor=MicroCompactor(recent_tool_results_keep=5, tool_result_preview_chars=60),
        auto_compaction_policy=AutoCompactionPolicy(
            trigger_fill_ratio=0.7,
            recover_fill_ratio=0.6,
            circuit_breaker_failures=3,
        ),
        summary_builder=StaticSummaryBuilder(),
        context_window_tokens=4,
        profile="compact-default",
        version="v1",
        enable_auto_compaction=True,
        enable_full_compaction=False,
    )

    original_messages = tuple(_message(index) for index in range(6))

    prepared_messages, prepared_state = manager.prepare_messages(
        messages=original_messages,
        task_plan=None,
        existing_state=None,
    )

    assert len(prepared_messages) < len(original_messages)
    assert prepared_state is not None
    assert prepared_state.latest_budget is not None
    assert prepared_state.latest_budget.estimated_tokens_used < len(original_messages)
    assert prepared_state.latest_budget.fill_ratio <= 1
    assert prepared_state.auto_compaction.last_compacted_turn == prepared_state.turn_count
    assert prepared_state.auto_compaction.fail_streak == 0
    assert prepared_state.auto_compaction.circuit_open is False


def test_context_manager_full_compaction_trims_after_summary_insertion_to_fit_budget() -> None:
    manager = ContextManager(
        budget_estimator=CountingBudgetEstimator(),
        micro_compactor=MicroCompactor(recent_tool_results_keep=5, tool_result_preview_chars=60),
        auto_compaction_policy=AutoCompactionPolicy(
            trigger_fill_ratio=0.9,
            recover_fill_ratio=0.8,
            circuit_breaker_failures=3,
        ),
        summary_builder=StaticSummaryBuilder(summary_text="Intent: summarized"),
        context_window_tokens=3,
        profile="compact-default",
        version="v1",
        enable_auto_compaction=False,
        enable_full_compaction=True,
    )

    prepared_messages, prepared_state = manager.prepare_messages(
        messages=tuple(_message(index) for index in range(8)),
        task_plan=None,
        existing_state=ContextManagementState(
            profile="compact-default",
            version="v1",
            auto_compaction=AutoCompactionState(),
        ),
    )

    assert prepared_messages[0].role == "system"
    assert "Compaction summary (compact-default v1)" in prepared_messages[0].content
    assert prepared_state is not None
    assert prepared_state.summary_snapshot is not None
    assert prepared_state.latest_budget is not None
    assert prepared_state.latest_budget.fill_ratio <= 1
    assert len(prepared_messages) <= 3
