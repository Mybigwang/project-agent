from __future__ import annotations

import tomllib
from pathlib import Path

from project_agent.errors import ConfigurationError
from project_agent.runtime.permissions.paths import is_protected_path, resolve_argument_paths
from project_agent.runtime.permissions.types import (
    PermissionDecision,
    PermissionMode,
    PermissionOutcome,
    PermissionRequest,
    PermissionRule,
    PermissionRuleAction,
    ToolPermissionCategory,
)

ALWAYS_DENIED_COMMAND_PREFIXES = (
    ("rm",),
    ("curl",),
    ("wget",),
    ("git", "reset", "--hard"),
)
DEFAULT_ALLOWED_COMMAND_PREFIXES = (
    ("git", "status"),
    ("git", "diff"),
    ("pytest",),
)


class PermissionPolicy:
    def __init__(self, *, mode: PermissionMode, rules: tuple[PermissionRule, ...] = ()) -> None:
        self._mode = mode
        self._rules = rules

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    def evaluate(self, request: PermissionRequest) -> PermissionOutcome:
        try:
            normalized_request = self._normalize_request(request)
        except Exception:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason_code="permission_normalization_failed",
                reason="permission request could not be normalized",
            )

        mode_outcome = self._evaluate_mode_hard_restrictions(normalized_request)
        if mode_outcome is not None:
            return mode_outcome

        deny_outcome = self._evaluate_rules(normalized_request, PermissionRuleAction.DENY)
        if deny_outcome is not None:
            return deny_outcome

        ask_outcome = self._evaluate_rules(normalized_request, PermissionRuleAction.ASK)
        if ask_outcome is not None:
            return ask_outcome

        safety_outcome = self._evaluate_safety_checks(normalized_request)
        if safety_outcome is not None:
            return safety_outcome

        allow_outcome = self._evaluate_rules(normalized_request, PermissionRuleAction.ALLOW)
        if allow_outcome is not None:
            return allow_outcome

        fallback_outcome = self._evaluate_mode_fallback(normalized_request)
        if fallback_outcome is not None:
            return fallback_outcome

        return PermissionOutcome(
            decision=PermissionDecision.DENY,
            reason_code="permission_fail_closed",
            reason="permission policy failed closed",
        )

    def _normalize_request(self, request: PermissionRequest) -> PermissionRequest:
        target_paths = request.target_paths
        if not target_paths:
            target_paths = resolve_argument_paths(
                workspace_root=request.workspace_root,
                arguments=request.arguments,
            )
        command_argv = request.command_argv
        if command_argv is None:
            argv = request.arguments.get("argv")
            if isinstance(argv, list) and argv and all(isinstance(item, str) for item in argv):
                command_argv = tuple(argv)
        return PermissionRequest(
            tool_name=request.tool_name,
            tool_category=request.tool_category,
            arguments=request.arguments,
            workspace_root=request.workspace_root,
            target_paths=target_paths,
            command_argv=command_argv,
            is_read_only=request.is_read_only,
        )

    def _evaluate_mode_hard_restrictions(
        self, request: PermissionRequest
    ) -> PermissionOutcome | None:
        if self._mode == PermissionMode.PLAN and request.tool_category in {
            ToolPermissionCategory.WRITE,
            ToolPermissionCategory.EXECUTE,
        }:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason_code="permission_plan_mode_denied",
                reason="plan mode only allows read and search tools",
            )
        return None

    def _evaluate_rules(
        self, request: PermissionRequest, action: PermissionRuleAction
    ) -> PermissionOutcome | None:
        for index, rule in enumerate(self._rules, start=1):
            if rule.action != action:
                continue
            if not self._rule_matches(rule, request):
                continue
            decision = {
                PermissionRuleAction.DENY: PermissionDecision.DENY,
                PermissionRuleAction.ASK: PermissionDecision.ASK,
                PermissionRuleAction.ALLOW: PermissionDecision.ALLOW,
            }[action]
            return PermissionOutcome(
                decision=decision,
                reason_code=f"permission_rule_{action.value}",
                reason=rule.reason or f"matched {action.value} rule",
                matched_rule=f"rule_{index}",
                requires_confirmation=decision == PermissionDecision.ASK,
            )
        return None

    def _rule_matches(self, rule: PermissionRule, request: PermissionRequest) -> bool:
        if rule.tool_name is not None and rule.tool_name != request.tool_name:
            return False
        if rule.tool_category is not None and rule.tool_category != request.tool_category:
            return False
        if rule.path_prefix is not None:
            if not request.target_paths:
                return False
            if not any(
                self._path_matches_prefix(request=request, path=path, prefix=rule.path_prefix)
                for path in request.target_paths
            ):
                return False
        if rule.command_prefix is not None:
            if request.command_argv is None:
                return False
            if request.command_argv[: len(rule.command_prefix)] != rule.command_prefix:
                return False
        return True

    def _path_matches_prefix(self, *, request: PermissionRequest, path: Path, prefix: str) -> bool:
        relative_path = path.resolve().relative_to(request.workspace_root.resolve()).as_posix()
        return relative_path == prefix or relative_path.startswith(f"{prefix}/")

    def _evaluate_safety_checks(self, request: PermissionRequest) -> PermissionOutcome | None:
        if request.tool_category == ToolPermissionCategory.WRITE and any(
            is_protected_path(workspace_root=request.workspace_root, path=path)
            for path in request.target_paths
        ):
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason_code="permission_protected_path",
                reason="writes to protected paths are denied",
            )

        if request.tool_category == ToolPermissionCategory.EXECUTE and request.command_argv is not None:
            for prefix in ALWAYS_DENIED_COMMAND_PREFIXES:
                if request.command_argv[: len(prefix)] == prefix:
                    return PermissionOutcome(
                        decision=PermissionDecision.DENY,
                        reason_code="permission_command_denied",
                        reason="command prefix is denied",
                    )
        return None

    def _evaluate_mode_fallback(self, request: PermissionRequest) -> PermissionOutcome | None:
        if request.tool_category in {ToolPermissionCategory.READ, ToolPermissionCategory.SEARCH}:
            return PermissionOutcome(
                decision=PermissionDecision.ALLOW,
                reason_code="permission_safe_read",
                reason="read and search tools are allowed",
            )

        if self._mode == PermissionMode.ACCEPT_EDITS and request.tool_category == ToolPermissionCategory.WRITE:
            return PermissionOutcome(
                decision=PermissionDecision.ALLOW,
                reason_code="permission_accept_edits",
                reason="write tool allowed in accept_edits mode",
            )

        if request.tool_category == ToolPermissionCategory.WRITE:
            if self._mode == PermissionMode.DONT_ASK:
                return PermissionOutcome(
                    decision=PermissionDecision.DENY,
                    reason_code="permission_dont_ask_write_denied",
                    reason="write tool denied without explicit allow rule in dont_ask mode",
                )
            return PermissionOutcome(
                decision=PermissionDecision.ASK,
                reason_code="permission_write_requires_approval",
                reason="write tool requires approval",
                requires_confirmation=True,
            )

        if request.tool_category == ToolPermissionCategory.EXECUTE:
            if request.command_argv is not None and any(
                request.command_argv[: len(prefix)] == prefix for prefix in DEFAULT_ALLOWED_COMMAND_PREFIXES
            ):
                return PermissionOutcome(
                    decision=PermissionDecision.ALLOW,
                    reason_code="permission_command_allowlist",
                    reason="command prefix is allowlisted",
                )
            if self._mode == PermissionMode.DONT_ASK:
                return PermissionOutcome(
                    decision=PermissionDecision.DENY,
                    reason_code="permission_dont_ask_command_denied",
                    reason="command denied without explicit allow rule in dont_ask mode",
                )
            return PermissionOutcome(
                decision=PermissionDecision.ASK,
                reason_code="permission_command_requires_approval",
                reason="command requires approval",
                requires_confirmation=True,
            )
        return None


def load_permission_rules(config_path: Path) -> tuple[PermissionRule, ...]:
    try:
        raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(f"failed to read permission rules file: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"failed to parse permission rules file: {config_path}") from error

    raw_rules = raw_config.get("rule", [])
    if not isinstance(raw_rules, list):
        raise ConfigurationError("invalid permission rules file")

    rules: list[PermissionRule] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ConfigurationError("invalid permission rule")
        action_value = raw_rule.get("action")
        if not isinstance(action_value, str):
            raise ConfigurationError("permission rule action is required")
        try:
            action = PermissionRuleAction(action_value)
        except ValueError as error:
            raise ConfigurationError(f"invalid permission rule action: {action_value}") from error

        tool_name = raw_rule.get("tool_name")
        if tool_name is not None and not isinstance(tool_name, str):
            raise ConfigurationError("invalid permission rule tool_name")

        tool_category_value = raw_rule.get("tool_category")
        tool_category = None
        if tool_category_value is not None:
            if not isinstance(tool_category_value, str):
                raise ConfigurationError("invalid permission rule tool_category")
            try:
                tool_category = ToolPermissionCategory(tool_category_value)
            except ValueError as error:
                raise ConfigurationError(
                    f"invalid permission rule tool_category: {tool_category_value}"
                ) from error

        path_prefix = raw_rule.get("path_prefix")
        if path_prefix is not None and not isinstance(path_prefix, str):
            raise ConfigurationError("invalid permission rule path_prefix")

        command_prefix_value = raw_rule.get("command_prefix")
        command_prefix = None
        if command_prefix_value is not None:
            if not isinstance(command_prefix_value, list) or not all(
                isinstance(item, str) for item in command_prefix_value
            ):
                raise ConfigurationError("invalid permission rule command_prefix")
            command_prefix = tuple(command_prefix_value)

        reason = raw_rule.get("reason", "")
        if not isinstance(reason, str):
            raise ConfigurationError("invalid permission rule reason")

        rules.append(
            PermissionRule(
                action=action,
                tool_name=tool_name,
                tool_category=tool_category,
                path_prefix=path_prefix,
                command_prefix=command_prefix,
                reason=reason,
            )
        )
    return tuple(rules)
