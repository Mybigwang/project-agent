from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from project_agent.core.interfaces import (
    ContextManagerProtocol,
    MemoryContextBuilderProtocol,
    ModelClient,
    RepositoryContextBuilderProtocol,
    SessionStore,
    Tool,
)
from project_agent.core.types import AgentSpec, Message, ToolCall, ToolResult
from project_agent.runtime.multi_agent import MultiAgentOrchestrator
from project_agent.runtime.permissions import PermissionMode, PermissionPolicy
from project_agent.skills import SkillPromptPreprocessor, SkillRegistry


class SubagentToolErrorRepairer:
    def __init__(
        self,
        *,
        orchestrator: MultiAgentOrchestrator,
        parent_session_id: str,
        model_client: ModelClient,
        tools: Sequence[Tool],
        session_store: SessionStore,
        max_steps: int,
        max_worker_result_chars: int,
        repository_context_builder: RepositoryContextBuilderProtocol | None = None,
        enable_repository_context: bool = False,
        memory_context_builder: MemoryContextBuilderProtocol | None = None,
        context_manager: ContextManagerProtocol | None = None,
        notification_callback: object | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_preprocessor: SkillPromptPreprocessor | None = None,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._parent_session_id = parent_session_id
        self._model_client = model_client
        self._tools = tuple(tool for tool in tools if tool.name != "agent")
        self._session_store = session_store
        self._max_steps = max_steps
        self._max_worker_result_chars = max_worker_result_chars
        self._repository_context_builder = repository_context_builder
        self._enable_repository_context = enable_repository_context
        self._memory_context_builder = memory_context_builder
        self._context_manager = context_manager
        self._notification_callback = notification_callback
        self._skill_registry = skill_registry
        self._skill_preprocessor = skill_preprocessor
        self._permission_policy = permission_policy

    def attempt_repair(
        self,
        *,
        user_input: str,
        recent_messages: Sequence[Message],
        tool_call: ToolCall,
        tool_result: ToolResult,
        workspace_root: Path,
    ) -> ToolResult | None:
        spec = AgentSpec(
            name="tool-error-repair",
            description=f"Repair failed tool call: {tool_call.name}",
            prompt=_build_repair_prompt(
                user_input=user_input,
                recent_messages=recent_messages,
                tool_call=tool_call,
                tool_result=tool_result,
            ),
            kind="worker",
            role="worker",
            subagent_type="worker",
            parent_session_id=self._parent_session_id,
            depth=1,
        )
        record = self._orchestrator.run_subagent(
            spec=spec,
            model_client=self._model_client,
            tools=self._tools,
            session_store=self._session_store,
            workspace_root=workspace_root,
            max_steps=self._max_steps,
            repository_context_builder=self._repository_context_builder,
            enable_repository_context=self._enable_repository_context,
            memory_context_builder=self._memory_context_builder,
            context_manager=self._context_manager,
            notification_callback=self._notification_callback,  # type: ignore[arg-type]
            skill_registry=self._skill_registry,
            skill_preprocessor=self._skill_preprocessor,
            permission_policy=_repair_permission_policy(self._permission_policy),
            approval_callback=None,
            max_worker_result_chars=self._max_worker_result_chars,
            parent_user_input=user_input,
        )
        if record.status != "completed":
            return None
        summary = record.result_summary or "repair subagent completed"
        return ToolResult(
            name=tool_call.name,
            content=summary,
            data={
                "repair_agent_id": record.agent_id,
                "repair_session_id": record.session_id,
                "repair_summary": summary,
                "repair_status": record.status,
                "repair_role": record.role,
            },
        )


def _repair_permission_policy(base_policy: PermissionPolicy | None) -> PermissionPolicy:
    if base_policy is not None:
        return base_policy
    return PermissionPolicy(mode=PermissionMode.DEFAULT, rules=())


def _build_repair_prompt(
    *,
    user_input: str,
    recent_messages: Sequence[Message],
    tool_call: ToolCall,
    tool_result: ToolResult,
) -> str:
    recent = "\n".join(
        f"- {message.role}: {message.content[:500]}" for message in recent_messages
    ) or "none"
    return (
        "A local tool call failed. Diagnose the error and, only if safe, perform a minimal retry or fix.\n"
        "Do not broaden scope. Do not spawn subagents. Do not use the agent tool.\n"
        "Return the useful final result for the parent agent, plus commands run and evidence in the required structured result.\n\n"
        f"Parent user request:\n{user_input}\n\n"
        f"Recent parent messages:\n{recent}\n\n"
        f"Failed tool name:\n{tool_call.name}\n\n"
        f"Failed tool arguments:\n{tool_call.arguments}\n\n"
        f"Structured tool error:\n{tool_result.to_message_content()}"
    )
