from __future__ import annotations

from project_agent.core.types import AutoCompactionState, BudgetSnapshot
from project_agent.runtime.context_management.auto_compaction import AutoCompactionPolicy


def _budget(fill_ratio: float) -> BudgetSnapshot:
    return BudgetSnapshot(
        estimated_tokens_used=int(fill_ratio * 100),
        estimated_tokens_limit=100,
        fill_ratio=fill_ratio,
        profile="compact-default",
        version="v1",
    )


def test_auto_compaction_policy_triggers_at_threshold() -> None:
    policy = AutoCompactionPolicy(
        trigger_fill_ratio=0.87,
        recover_fill_ratio=0.82,
        circuit_breaker_failures=3,
    )

    assert policy.should_compact(budget=_budget(0.9), state=AutoCompactionState()) is True
    assert policy.should_compact(budget=_budget(0.8), state=AutoCompactionState()) is False


def test_auto_compaction_policy_opens_circuit_after_failures() -> None:
    policy = AutoCompactionPolicy(
        trigger_fill_ratio=0.87,
        recover_fill_ratio=0.82,
        circuit_breaker_failures=3,
    )
    state = AutoCompactionState()

    state = policy.record_failure(state=state, budget=_budget(0.9), error="boom")
    state = policy.record_failure(state=state, budget=_budget(0.9), error="boom")
    state = policy.record_failure(state=state, budget=_budget(0.9), error="boom")

    assert state.circuit_open is True
    assert state.fail_streak == 3
