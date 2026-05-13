from __future__ import annotations

from collections.abc import Sequence

from project_agent.core.interfaces import (
    CompactionSummaryBuilderProtocol,
    ContextBudgetEstimatorProtocol,
)
from project_agent.core.types import BudgetSnapshot, ContextManagementState, Message, TaskPlan
from project_agent.runtime.context_management.auto_compaction import AutoCompactionPolicy
from project_agent.runtime.context_management.micro_compaction import MicroCompactor


class ContextManager:
    def __init__(
        self,
        *,
        budget_estimator: ContextBudgetEstimatorProtocol,
        micro_compactor: MicroCompactor,
        auto_compaction_policy: AutoCompactionPolicy,
        summary_builder: CompactionSummaryBuilderProtocol,
        context_window_tokens: int,
        profile: str,
        version: str,
        enable_auto_compaction: bool,
        enable_full_compaction: bool,
    ) -> None:
        self.budget_estimator = budget_estimator
        self.micro_compactor = micro_compactor
        self.auto_compaction_policy = auto_compaction_policy
        self.summary_builder = summary_builder
        self.context_window_tokens = context_window_tokens
        self.profile = profile
        self.version = version
        self.enable_auto_compaction = enable_auto_compaction
        self.enable_full_compaction = enable_full_compaction

    def prepare_messages(
        self,
        *,
        messages: Sequence[Message],
        task_plan: TaskPlan | None,
        existing_state: ContextManagementState | None,
    ) -> tuple[tuple[Message, ...], ContextManagementState | None]:
        state = existing_state or ContextManagementState(profile=self.profile, version=self.version)
        compacted_messages = self.micro_compactor.compact_messages(messages)
        budget = self._estimate(compacted_messages)
        auto_state = self.auto_compaction_policy.update_without_compaction(
            state=state.auto_compaction,
            budget=budget,
        )
        updated_state = ContextManagementState(
            profile=self.profile,
            version=self.version,
            turn_count=state.turn_count + 1,
            latest_budget=budget,
            auto_compaction=auto_state,
            summary_snapshot=state.summary_snapshot,
        )

        if self.enable_auto_compaction and self.auto_compaction_policy.should_compact(
            budget=budget,
            state=state.auto_compaction,
        ):
            auto_compacted_messages = self._trim_to_budget(compacted_messages)
            auto_compacted_budget = self._estimate(auto_compacted_messages)
            if auto_compacted_budget.estimated_tokens_used < budget.estimated_tokens_used:
                compacted_messages = auto_compacted_messages
                budget = auto_compacted_budget
                auto_state = self.auto_compaction_policy.record_success(
                    state=auto_state,
                    budget=budget,
                    turn_count=updated_state.turn_count,
                )
            else:
                auto_state = self.auto_compaction_policy.record_failure(
                    state=auto_state,
                    budget=budget,
                    error="auto compaction did not reduce prompt size",
                )
            updated_state = ContextManagementState(
                profile=self.profile,
                version=self.version,
                turn_count=updated_state.turn_count,
                latest_budget=budget,
                auto_compaction=auto_state,
                summary_snapshot=updated_state.summary_snapshot,
            )

        if self.enable_full_compaction and budget.fill_ratio >= 1:
            summary_snapshot = self.summary_builder.build_summary(
                messages=compacted_messages,
                task_plan=task_plan,
                existing_state=updated_state,
            )
            summary_message = Message(
                role="system",
                content=(
                    f"Compaction summary ({summary_snapshot.profile} {summary_snapshot.version})\n\n"
                    f"{summary_snapshot.summary_text}"
                ),
            )
            compacted_messages = self._trim_to_budget((summary_message, *compacted_messages[-6:]))
            budget = self._estimate(compacted_messages)
            updated_state = ContextManagementState(
                profile=self.profile,
                version=self.version,
                turn_count=updated_state.turn_count,
                latest_budget=budget,
                auto_compaction=updated_state.auto_compaction,
                summary_snapshot=summary_snapshot,
            )
            return compacted_messages, updated_state
        return compacted_messages, updated_state

    def _estimate(self, messages: Sequence[Message]) -> BudgetSnapshot:
        return self.budget_estimator.estimate_messages(
            messages=messages,
            token_limit=self.context_window_tokens,
            profile=self.profile,
            version=self.version,
        )

    def _trim_to_budget(self, messages: Sequence[Message]) -> tuple[Message, ...]:
        trimmed_messages = tuple(messages)
        while trimmed_messages:
            budget = self._estimate(trimmed_messages)
            if budget.fill_ratio <= 1:
                return trimmed_messages
            if len(trimmed_messages) <= 1:
                return trimmed_messages
            trimmed_messages = (trimmed_messages[0], *trimmed_messages[2:])
        return tuple(messages)
