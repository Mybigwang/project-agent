from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
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
from project_agent.core.types import AgentRole, AgentSpec, ToolResult
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
            "subagent_type": {
                "type": "string",
                "enum": ["explore", "plan", "worker", "verification", "generalPurpose"],
            },
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
        default_role: AgentRole = "generalPurpose",
        strict_task_specs: bool = True,
        parent_depth: int = 0,
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
        self._default_role = default_role
        self._strict_task_specs = strict_task_specs
        self._parent_depth = parent_depth
        self._calls = 0

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        del workspace_root
        if self._parent_depth > 0:
            return ToolResult(
                name=self.name,
                content="recursive subagents are denied",
                is_error=True,
                error_code="recursive_subagents_denied",
            )
        self._calls += 1
        if self._calls > self._max_subagents:
            return ToolResult(
                name=self.name,
                content="maximum subagents per turn exceeded",
                is_error=True,
                error_code="max_subagents_exceeded",
            )
        try:
            spec = _parse_agent_spec(
                arguments,
                parent_session_id=self._parent_session_id,
                default_role=self._default_role,
                parent_depth=self._parent_depth,
                strict_task_specs=self._strict_task_specs,
            )
        except AgentSpecError as error:
            return ToolResult(
                name=self.name,
                content=str(error),
                is_error=True,
                error_code=error.error_code,
            )
        if spec.run_in_background:
            ticket = self._orchestrator.run_subagent_in_background(
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
            return ToolResult(
                name=self.name,
                content=(
                    "<task-ticket>\n"
                    f"<task-id>{ticket.task_id}</task-id>\n"
                    f"<status>{ticket.status}</status>\n"
                    "</task-ticket>"
                ),
                data={
                    "task_id": ticket.task_id,
                    "status": ticket.status,
                    "run_in_background": True,
                },
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
        notification_record = record_to_notification(record)
        safe_notification_record = replace(
            notification_record,
            result=truncate_worker_result(
                notification_record.result,
                self._max_worker_result_chars,
            ),
        )
        safe_result = format_task_notification(safe_notification_record)
        structured_result = record.structured_result
        return ToolResult(
            name=self.name,
            content=safe_result,
            is_error=record.status == "failed",
            data={
                "agent_id": record.agent_id,
                "session_id": record.session_id,
                "status": record.status,
                "summary": record.result_summary or record.description,
                "role": record.role,
                "verdict": record.verdict,
                "evidence": list(structured_result.evidence) if structured_result else [],
                "touched_files": (
                    list(structured_result.touched_files) if structured_result else []
                ),
                "commands_run": (
                    list(structured_result.commands_run) if structured_result else []
                ),
                "open_questions": (
                    list(structured_result.open_questions) if structured_result else []
                ),
                "result": safe_result,
                "result_trust": "untrusted-worker-output",
            },
        )


class AgentSpecError(ValueError):
    def __init__(self, message: str, *, error_code: str = "invalid_agent_request") -> None:
        super().__init__(message)
        self.error_code = error_code


def _parse_agent_spec(
    arguments: dict[str, object],
    *,
    parent_session_id: str,
    default_role: AgentRole,
    parent_depth: int,
    strict_task_specs: bool,
) -> AgentSpec:
    description = arguments.get("description")
    prompt = arguments.get("prompt")
    name = arguments.get("name")
    subagent_type = arguments.get("subagent_type")
    model = arguments.get("model")
    run_in_background = arguments.get("run_in_background", False)
    if not isinstance(description, str) or not description.strip():
        raise AgentSpecError("description must be a non-empty string")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AgentSpecError("prompt must be a non-empty string")
    for field_name, value in {
        "name": name,
        "subagent_type": subagent_type,
        "model": model,
    }.items():
        if value is not None and not isinstance(value, str):
            raise AgentSpecError(f"{field_name} must be a string")
    if not isinstance(run_in_background, bool):
        raise AgentSpecError("run_in_background must be a boolean")
    role = _parse_role(subagent_type, default_role=default_role)
    prompt_text = prompt.strip()
    if strict_task_specs:
        _validate_task_spec(role=role, prompt=prompt_text, description=description.strip())
    agent_name = _optional_string(name)
    return AgentSpec(
        name=agent_name,
        description=description.strip(),
        prompt=prompt_text,
        kind="worker",
        role=role,
        subagent_type=role,
        model=_optional_string(model),
        run_in_background=run_in_background,
        parent_session_id=parent_session_id,
        depth=parent_depth,
    )


def _parse_role(value: object, *, default_role: AgentRole) -> AgentRole:
    role = _optional_string(value) or default_role
    allowed_roles = {"explore", "plan", "worker", "verification", "generalPurpose"}
    if role == "coordinator":
        raise AgentSpecError(
            "coordinator role cannot run as a child agent",
            error_code="role_not_allowed",
        )
    if role not in allowed_roles:
        raise AgentSpecError(f"unknown subagent_type: {role}", error_code="role_not_allowed")
    return role  # type: ignore[return-value]


def _validate_task_spec(*, role: AgentRole, prompt: str, description: str) -> None:
    text = f"{description}\n{prompt}".lower()
    lazy_phrases = (
        "fix it",
        "figure it out",
        "make it better",
        "do everything",
        "handle everything",
        "based on your findings fix",
    )
    if any(phrase in text for phrase in lazy_phrases):
        raise AgentSpecError("agent task spec is too vague", error_code="task_spec_too_vague")
    if role in {"worker", "generalPurpose"} and not _has_worker_specificity(text):
        raise AgentSpecError(
            "worker task spec must include a path, scope, acceptance criteria, "
            "or verification guidance",
            error_code="task_spec_too_vague",
        )
    if role == "verification" and not _has_verification_intent(text):
        raise AgentSpecError(
            "verification task spec must include a test, check, lint, build, "
            "probe, or verify instruction",
            error_code="task_spec_too_vague",
        )


def _has_worker_specificity(text: str) -> bool:
    return any(
        token in text
        for token in ("/", ".py", "test", "verify", "accept", "scope", "file")
    )


def _has_verification_intent(text: str) -> bool:
    return any(
        token in text
        for token in ("test", "pytest", "check", "lint", "build", "probe", "verify")
    )


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
