from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from project_agent.core.types import Message
from project_agent.errors import AgentError

TOPIC_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
SECRET_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})\b"
    r"|(?i:\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[\"']?[^\s\"',}]{4,})"
)


def redact(text: str) -> str:
    return SECRET_PATTERN.sub("[REDACTED]", text)


def check_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AgentError("invalid memory text or size")
    if SECRET_PATTERN.search(value) or "[REDACTED]" in value:
        raise AgentError("memory contains a possible credential")
    return value.strip()


def check_topic(value: object) -> str:
    if not isinstance(value, str) or not TOPIC_PATTERN.fullmatch(value):
        raise AgentError("memory topic must be a lowercase slug, at most 64 characters")
    # Also prevent reserved device filenames on Windows.
    if value in {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }:
        raise AgentError("reserved memory topic")
    return value


def json_response(response: object) -> dict[str, Any]:
    if not isinstance(response, Message):
        raise AgentError("memory model must return a JSON message")
    try:
        value = json.loads(response.content)
    except json.JSONDecodeError as error:
        raise AgentError("memory model returned invalid JSON") from error
    if not isinstance(value, dict):
        raise AgentError("memory model must return a JSON object")
    return value


@dataclass(frozen=True)
class MemoryCandidate:
    topic: str
    content: str
    evidence: str
    source_session_id: str
    created_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemoryCandidate:
        return cls(
            topic=check_topic(value["topic"]),
            content=check_text(value["content"], limit=2000),
            evidence=check_text(value["evidence"], limit=1000),
            source_session_id=check_text(value["source_session_id"], limit=200),
            created_at=float(value["created_at"]),
        )


@dataclass(frozen=True)
class TopicUpdate:
    topic: str
    content: str
    sources: tuple[str, ...]
