from __future__ import annotations

from collections.abc import Sequence

from project_agent.core.types import BudgetSnapshot, Message


class HeuristicTokenEstimator:
    def estimate_text(self, text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)

    def estimate_messages(
        self,
        *,
        messages: Sequence[Message],
        token_limit: int,
        profile: str,
        version: str,
    ) -> BudgetSnapshot:
        estimated_tokens_used = sum(
            self.estimate_text(message.content) + self.estimate_text(message.role)
            for message in messages
        )
        fill_ratio = estimated_tokens_used / token_limit if token_limit else 1.0
        return BudgetSnapshot(
            estimated_tokens_used=estimated_tokens_used,
            estimated_tokens_limit=token_limit,
            fill_ratio=fill_ratio,
            profile=profile,
            version=version,
        )
