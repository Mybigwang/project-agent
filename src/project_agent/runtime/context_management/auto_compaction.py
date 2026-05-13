from __future__ import annotations

from dataclasses import replace

from project_agent.core.types import AutoCompactionState, BudgetSnapshot


class AutoCompactionPolicy:
    def __init__(
        self,
        *,
        trigger_fill_ratio: float,
        recover_fill_ratio: float,
        circuit_breaker_failures: int,
    ) -> None:
        self.trigger_fill_ratio = trigger_fill_ratio
        self.recover_fill_ratio = recover_fill_ratio
        self.circuit_breaker_failures = circuit_breaker_failures

    def should_compact(self, *, budget: BudgetSnapshot, state: AutoCompactionState) -> bool:
        if state.circuit_open:
            return False
        if budget.fill_ratio >= self.trigger_fill_ratio:
            return True
        if state.last_fill_ratio is not None and state.last_fill_ratio >= self.trigger_fill_ratio:
            return budget.fill_ratio > self.recover_fill_ratio
        return False

    def record_success(
        self,
        *,
        state: AutoCompactionState,
        budget: BudgetSnapshot,
        turn_count: int,
    ) -> AutoCompactionState:
        return AutoCompactionState(
            fail_streak=0,
            last_fill_ratio=budget.fill_ratio,
            circuit_open=False,
            last_error=None,
            last_compacted_turn=turn_count,
        )

    def record_failure(
        self,
        *,
        state: AutoCompactionState,
        budget: BudgetSnapshot,
        error: str,
    ) -> AutoCompactionState:
        fail_streak = state.fail_streak + 1
        return AutoCompactionState(
            fail_streak=fail_streak,
            last_fill_ratio=budget.fill_ratio,
            circuit_open=fail_streak >= self.circuit_breaker_failures,
            last_error=error,
            last_compacted_turn=state.last_compacted_turn,
        )

    def update_without_compaction(
        self,
        *,
        state: AutoCompactionState,
        budget: BudgetSnapshot,
    ) -> AutoCompactionState:
        if state.circuit_open and budget.fill_ratio <= self.recover_fill_ratio:
            return replace(state, circuit_open=False, fail_streak=0, last_error=None, last_fill_ratio=budget.fill_ratio)
        return replace(state, last_fill_ratio=budget.fill_ratio)
