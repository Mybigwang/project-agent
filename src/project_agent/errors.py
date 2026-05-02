from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentError(Exception):
    message: str
    exit_code: int = 1

    def __str__(self) -> str:
        return self.message


class ConfigurationError(AgentError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, exit_code=2)


class ToolExecutionError(AgentError):
    pass


class RuntimeLimitError(AgentError):
    def __init__(self, max_steps: int) -> None:
        super().__init__(message=f"agent runtime exceeded max_steps={max_steps}")


class SessionError(AgentError):
    pass


def map_exception_to_exit_code(error: Exception) -> int:
    if isinstance(error, AgentError):
        return error.exit_code
    return 1
