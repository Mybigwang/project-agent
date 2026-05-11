from pathlib import Path

from project_agent.runtime.permissions import (
    PermissionDecision,
    PermissionMode,
    PermissionPolicy,
    PermissionRequest,
    PermissionRule,
    PermissionRuleAction,
    ToolPermissionCategory,
)


def _request(
    tmp_path: Path,
    *,
    tool_name: str,
    tool_category: ToolPermissionCategory,
    arguments: dict[str, object] | None = None,
) -> PermissionRequest:
    return PermissionRequest(
        tool_name=tool_name,
        tool_category=tool_category,
        arguments=arguments or {},
        workspace_root=tmp_path,
        is_read_only=tool_category in {ToolPermissionCategory.READ, ToolPermissionCategory.SEARCH},
    )


def test_plan_mode_denies_write_tool(tmp_path: Path) -> None:
    policy = PermissionPolicy(mode=PermissionMode.PLAN)

    outcome = policy.evaluate(
        _request(tmp_path, tool_name="write_file", tool_category=ToolPermissionCategory.WRITE)
    )

    assert outcome.decision == PermissionDecision.DENY
    assert outcome.reason_code == "permission_plan_mode_denied"


def test_default_mode_asks_for_write_tool(tmp_path: Path) -> None:
    policy = PermissionPolicy(mode=PermissionMode.DEFAULT)

    outcome = policy.evaluate(
        _request(tmp_path, tool_name="write_file", tool_category=ToolPermissionCategory.WRITE)
    )

    assert outcome.decision == PermissionDecision.ASK
    assert outcome.reason_code == "permission_write_requires_approval"


def test_accept_edits_mode_allows_write_tool(tmp_path: Path) -> None:
    policy = PermissionPolicy(mode=PermissionMode.ACCEPT_EDITS)

    outcome = policy.evaluate(
        _request(tmp_path, tool_name="edit_file", tool_category=ToolPermissionCategory.WRITE)
    )

    assert outcome.decision == PermissionDecision.ALLOW
    assert outcome.reason_code == "permission_accept_edits"


def test_dont_ask_mode_denies_non_allowlisted_command(tmp_path: Path) -> None:
    policy = PermissionPolicy(mode=PermissionMode.DONT_ASK)

    outcome = policy.evaluate(
        _request(
            tmp_path,
            tool_name="run_command",
            tool_category=ToolPermissionCategory.EXECUTE,
            arguments={"argv": ["python", "-V"]},
        )
    )

    assert outcome.decision == PermissionDecision.DENY
    assert outcome.reason_code == "permission_dont_ask_command_denied"


def test_policy_denies_protected_write_path(tmp_path: Path) -> None:
    policy = PermissionPolicy(mode=PermissionMode.ACCEPT_EDITS)

    outcome = policy.evaluate(
        _request(
            tmp_path,
            tool_name="write_file",
            tool_category=ToolPermissionCategory.WRITE,
            arguments={"path": ".git/config", "content": "x"},
        )
    )

    assert outcome.decision == PermissionDecision.DENY
    assert outcome.reason_code == "permission_protected_path"


def test_policy_denies_blocked_command_prefix(tmp_path: Path) -> None:
    policy = PermissionPolicy(mode=PermissionMode.DEFAULT)

    outcome = policy.evaluate(
        _request(
            tmp_path,
            tool_name="run_command",
            tool_category=ToolPermissionCategory.EXECUTE,
            arguments={"argv": ["rm", "-rf", "tmp"]},
        )
    )

    assert outcome.decision == PermissionDecision.DENY
    assert outcome.reason_code == "permission_command_denied"


def test_deny_rule_wins_before_allow_rule(tmp_path: Path) -> None:
    policy = PermissionPolicy(
        mode=PermissionMode.DEFAULT,
        rules=(
            PermissionRule(
                action=PermissionRuleAction.DENY,
                tool_name="run_command",
                reason="deny first",
            ),
            PermissionRule(
                action=PermissionRuleAction.ALLOW,
                tool_name="run_command",
                reason="allow second",
            ),
        ),
    )

    outcome = policy.evaluate(
        _request(
            tmp_path,
            tool_name="run_command",
            tool_category=ToolPermissionCategory.EXECUTE,
            arguments={"argv": ["git", "status"]},
        )
    )

    assert outcome.decision == PermissionDecision.DENY
    assert outcome.reason_code == "permission_rule_deny"


def test_allow_rule_does_not_override_protected_path_denial(tmp_path: Path) -> None:
    policy = PermissionPolicy(
        mode=PermissionMode.ACCEPT_EDITS,
        rules=(
            PermissionRule(
                action=PermissionRuleAction.ALLOW,
                tool_name="write_file",
                path_prefix=".git",
                reason="allow write",
            ),
        ),
    )

    outcome = policy.evaluate(
        _request(
            tmp_path,
            tool_name="write_file",
            tool_category=ToolPermissionCategory.WRITE,
            arguments={"path": ".git/config", "content": "x"},
        )
    )

    assert outcome.decision == PermissionDecision.DENY
    assert outcome.reason_code == "permission_protected_path"
