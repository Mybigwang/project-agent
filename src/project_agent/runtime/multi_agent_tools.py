from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from project_agent.core.interfaces import (
    ContextManagerProtocol,
    MemoryContextBuilderProtocol,
    ModelClient,
    RepositoryContextBuilderProtocol,
    SessionStore,
    Tool,
)
from project_agent.core.types import AgentSpec, ToolResult
from project_agent.runtime.agent import ApprovalCallback, NotificationCallback
from project_agent.runtime.multi_agent import (
    MultiAgentOrchestrator,
    format_task_notification,
    record_to_notification,
    truncate_worker_result,
)
from project_agent.runtime.permissions import PermissionPolicy, ToolPermissionCategory
from project_agent.skills import SkillPromptPreprocessor, SkillRegistry


class SubagentTool:
    name = "agent"
    description = "Run a focused subagent worker for a delegated task."
    input_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "prompt": {"type": "string"},
            "subagent_type": {"type": "string"},
            "model": {"type": "string"},
            "run_in_background": {"type": "boolean"},
            "name": {"type": "string"},
        },
        "required": ["description", "prompt"],
    }
    is_read_only = False
    permission_category = ToolPermissionCategory.EXECUTE

    def __init__(
        self,
        *,
        orchestrator: MultiAgentOrchestrator,
        parent_session_id: str,
        model_client: ModelClient,
        tools: Sequence[Tool],
        session_store: SessionStore,
        workspace_root: Path,
        max_steps: int,
        max_subagents: int,
        max_worker_result_chars: int,
        repository_context_builder: RepositoryContextBuilderProtocol | None = None,
        enable_repository_context: bool = True,
        memory_context_builder: MemoryContextBuilderProtocol | None = None,
        context_manager: ContextManagerProtocol | None = None,
        notification_callback: NotificationCallback | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_preprocessor: SkillPromptPreprocessor | None = None,
        permission_policy: PermissionPolicy | None = None,
        approval_callback: ApprovalCallback | None = None,
        parent_user_input: str | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._parent_session_id = parent_session_id
        self._model_client = model_client
        self._tools = tuple(tool for tool in tools if tool.name != self.name)
        self._session_store = session_store
        self._workspace_root = workspace_root
        self._max_steps = max_steps
        self._max_subagents = max_subagents
        self._max_worker_result_chars = max_worker_result_chars
        self._repository_context_builder = repository_context_builder
        self._enable_repository_context = enable_repository_context
        self._memory_context_builder = memory_context_builder
        self._context_manager = context_manager
        self._notification_callback = notification_callback
        self._skill_registry = skill_registry
        self._skill_preprocessor = skill_preprocessor
        self._permission_policy = permission_policy
        self._approval_callback = approval_callback
        self._parent_user_input = parent_user_input
        self._calls = 0

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        del workspace_root
        self._calls += 1
        if self._calls > self._max_subagents:
            return ToolResult(
                name=self.name,
                content="maximum subagents per turn exceeded",
                is_error=True,
                error_code="max_subagents_exceeded",
            )
        if arguments.get("run_in_background") is True:
            return ToolResult(
                name=self.name,
                content="run_in_background is not supported yet",
                is_error=True,
                error_code="background_not_supported",
            )
        try:
            spec = _parse_agent_spec(arguments, parent_session_id=self._parent_session_id)
        except ValueError as error:
            return ToolResult(
                name=self.name,
                content=str(error),
                is_error=True,
                error_code="invalid_agent_request",
            )
        record = self._orchestrator.run_subagent(
            spec=spec,
            model_client=self._model_client,
            tools=self._tools,
            session_store=self._session_store,
            workspace_root=self._workspace_root,
            max_steps=self._max_steps,
            repository_context_builder=self._repository_context_builder,
            enable_repository_context=self._enable_repository_context,
            memory_context_builder=self._memory_context_builder,
            context_manager=self._context_manager,
            notification_callback=self._notification_callback,
            skill_registry=self._skill_registry,
            skill_preprocessor=self._skill_preprocessor,
            permission_policy=self._permission_policy,
            approval_callback=self._approval_callback,
            max_worker_result_chars=self._max_worker_result_chars,
            parent_user_input=self._parent_user_input,
        )
        notification = format_task_notification(record_to_notification(record))
        safe_result = truncate_worker_result(
            notification,
            self._max_worker_result_chars,
        )
        return ToolResult(
            name=self.name,
            content=notification,
            is_error=record.status == "failed",
            data={
                "agent_id": record.agent_id,
                "session_id": record.session_id,
                "status": record.status,
                "summary": record.description,
                "result": safe_result,
                "result_trust": "untrusted-worker-output",
            },
        )


def _parse_agent_spec(arguments: dict[str, object], *, parent_session_id: str) -> AgentSpec:
    description = arguments.get("description")
    prompt = arguments.get("prompt")
    name = arguments.get("name")
    subagent_type = arguments.get("subagent_type")
    model = arguments.get("model")
    run_in_background = arguments.get("run_in_background", False)
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    for field_name, value in {
        "name": name,
        "subagent_type": subagent_type,
        "model": model,
    }.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
    if not isinstance(run_in_background, bool):
        raise ValueError("run_in_background must be a boolean")
    agent_name = _optional_string(name)
    return AgentSpec(
        name=agent_name,
        description=description.strip(),
        prompt=prompt.strip(),
        kind="worker",
        subagent_type=_optional_string(subagent_type),
        model=_optional_string(model),
        run_in_background=run_in_background,
        parent_session_id=parent_session_id,
    )


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
