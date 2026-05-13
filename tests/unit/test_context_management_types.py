from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from project_agent.core.types import ContextManagementState, SessionState


def test_session_state_supports_optional_context_management_state() -> None:
    state = SessionState(
        context_state=ContextManagementState(profile="compact-default", version="v1")
    )

    assert state.context_state is not None
    assert state.context_state.profile == "compact-default"


def test_context_management_state_is_immutable() -> None:
    state = ContextManagementState(profile="compact-default", version="v1")

    with pytest.raises(FrozenInstanceError):
        state.profile = "other"  # type: ignore[misc]
