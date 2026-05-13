from __future__ import annotations

from project_agent.core.types import Message
from project_agent.runtime.context_management.budget import HeuristicTokenEstimator


def test_heuristic_token_estimator_counts_message_content() -> None:
    estimator = HeuristicTokenEstimator()

    snapshot = estimator.estimate_messages(
        messages=(
            Message(role="user", content="abcd"),
            Message(role="assistant", content="abcdefgh"),
        ),
        token_limit=20,
        profile="compact-default",
        version="v1",
    )

    assert snapshot.estimated_tokens_used >= 5
    assert snapshot.estimated_tokens_limit == 20
    assert snapshot.profile == "compact-default"
    assert snapshot.version == "v1"
