from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    PLAN = "plan"
    DONT_ASK = "dont_ask"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionRuleAction(str, Enum):
    DENY = "deny"
    ASK = "ask"
    ALLOW = "allow"


class ToolPermissionCategory(str, Enum):
    READ = "read"
    WRITE = "write"
    SEARCH = "search"
    EXECUTE = "execute"


@dataclass(frozen=True)
class PermissionRule:
    action: PermissionRuleAction
    tool_name: str | None = None
    tool_category: ToolPermissionCategory | None = None
    path_prefix: str | None = None
    command_prefix: tuple[str, ...] | None = None
    reason: str = ""


@dataclass(frozen=True)
class PermissionRequest:
    tool_name: str
    tool_category: ToolPermissionCategory
    arguments: dict[str, Any]
    workspace_root: Path
    target_paths: tuple[Path, ...] = ()
    command_argv: tuple[str, ...] | None = None
    is_read_only: bool = False


@dataclass(frozen=True)
class PermissionOutcome:
    decision: PermissionDecision
    reason_code: str
    reason: str
    matched_rule: str | None = None
    requires_confirmation: bool = False
