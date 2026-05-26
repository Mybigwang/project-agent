from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from project_agent.core.interfaces import (
    ContextManagerProtocol,
    MemoryContextBuilderProtocol,
    ModelClient,
    Planner,
    RepositoryContextBuilderProtocol,
    SessionStore,
    Tool,
)
from project_agent.core.types import (
    AgentTraceStep,
    ContextManagementState,
    MemoryContext,
    Message,
    RunResult,
    SessionState,
    SkillCall,
    Task,
    TaskPlan,
    ToolCall,
    ToolResult,
)
from project_agent.errors import AgentError, RuntimeLimitError
from project_agent.runtime.model_clients import MAX_TOOL_CALLS_PER_RESPONSE
from project_agent.runtime.permissions import (
    PermissionDecision,
    PermissionPolicy,
    PermissionRequest,
)
from project_agent.runtime.tool_registry import ToolRegistry
from project_agent.skills import (
    SkillPromptPreprocessor,
    SkillRegistry,
    build_skill_invocation,
)
from project_agent.skills.errors import SkillError

LOGGER = logging.getLogger(__name__)
MAX_SKILL_CALLS_PER_TURN = 1
NotificationCallback = Callable[[str], None]
ApprovalCallback = Callable[[str], bool]


class AgentRuntime:
    def run_turn(
        self,
        *,
        session_id: str,
        user_input: str,
        model_client: ModelClient,
        tools: Sequence[Tool],
        session_store: SessionStore,
        workspace_root: Path,
        max_steps: int,
        repository_context_builder: RepositoryContextBuilderProtocol | None = None,
        enable_repository_context: bool = True,
        memory_context_builder: MemoryContextBuilderProtocol | None = None,
        planner: Planner | None = None,
        context_manager: ContextManagerProtocol | None = None,
        stream_callback: Callable[[str], None] | None = None,
        notification_callback: NotificationCallback | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_preprocessor: SkillPromptPreprocessor | None = None,
        permission_policy: PermissionPolicy | None = None,
        approval_callback: ApprovalCallback | None = None,
        system_prefix_messages: Sequence[Message] = (),
    ) -> RunResult:
        state = session_store.load(session_id)
        history = state.messages
        messages = history + (Message(role="user", content=user_input),)
        registry = ToolRegistry(tools)
        memory_context = self._build_memory_context(
            memory_context_builder=memory_context_builder,
            user_input=user_input,
        )
        if notification_callback is not None:
            self._notify_memory_recall(
                memory_context=memory_context,
                notification_callback=notification_callback,
            )
        if planner is None:
            return self._run_message_loop(
                session_id=session_id,
                user_input=user_input,
                history=history,
                messages=messages,
                model_client=model_client,
                registry=registry,
                session_store=session_store,
                workspace_root=workspace_root,
                max_steps=max_steps,
                repository_context_builder=repository_context_builder,
                enable_repository_context=enable_repository_context,
                memory_context=memory_context,
                context_manager=context_manager,
                stream_callback=stream_callback,
                notification_callback=notification_callback,
                skill_registry=skill_registry,
                skill_preprocessor=skill_preprocessor,
                permission_policy=permission_policy,
                approval_callback=approval_callback,
                system_prefix_messages=tuple(system_prefix_messages),
            )

        task_plan = self._select_task_plan(
            existing_task_plan=state.task_plan,
            planner=planner,
            user_input=user_input,
            history=history,
        )
        trace: tuple[AgentTraceStep, ...] = ()
        final_message: Message | None = None
        step = 1
        context_state = state.context_state
        task_plan = self._refresh_blocked_statuses(task_plan)

        while True:
            task = self._next_executable_task(task_plan)
            if task is None:
                break
            task_plan = self._mark_task_status(task_plan, task.id, "in_progress")
            trace = trace + (
                AgentTraceStep(
                    step=step,
                    event="task",
                    summary=f"started {task.title}",
                    task_id=task.id,
                    task_status="in_progress",
                ),
            )
            step += 1
            task_result = self._run_task(
                task=self._require_task(task_plan, task.id),
                task_plan=task_plan,
                user_input=user_input,
                history=history,
                messages=messages,
                model_client=model_client,
                registry=registry,
                workspace_root=workspace_root,
                max_steps=max_steps,
                start_step=step,
                repository_context_builder=repository_context_builder,
                enable_repository_context=enable_repository_context,
                memory_context=memory_context,
                context_manager=context_manager,
                stream_callback=stream_callback,
                notification_callback=notification_callback,
                skill_registry=skill_registry,
                skill_preprocessor=skill_preprocessor,
                permission_policy=permission_policy,
                approval_callback=approval_callback,
                existing_context_state=context_state,
                system_prefix_messages=tuple(system_prefix_messages),
            )
            messages = task_result.messages
            trace = trace + task_result.trace
            step = task_result.next_step
            context_state = task_result.context_state
            if task_result.error is None and task_result.final_message is not None:
                final_message = task_result.final_message
                task_plan = self._mark_task_status(task_plan, task.id, "completed")
                trace = trace + (
                    AgentTraceStep(
                        step=step,
                        event="task",
                        summary=f"completed {task.title}",
                        task_id=task.id,
                        task_status="completed",
                    ),
                )
                step += 1
                task_plan = self._refresh_blocked_statuses(task_plan)
                continue

            error = task_result.error or "task failed"
            failed_task = self._require_task(task_plan, task.id)
            if failed_task.attempts < 1:
                task_plan = self._mark_task_status(
                    task_plan,
                    task.id,
                    "pending",
                    last_error=error,
                    attempts_increment=True,
                )
                trace = trace + (
                    AgentTraceStep(
                        step=step,
                        event="task",
                        summary=f"retrying {task.title}: {error}",
                        task_id=task.id,
                        task_status="pending",
                        is_error=True,
                    ),
                )
                step += 1
                continue

            task_plan = planner.replan_after_failure(
                user_input=user_input,
                history=history,
                task_plan=self._mark_task_status(
                    task_plan, task.id, "blocked", last_error=error
                ),
                failed_task_id=task.id,
                error=error,
            )
            final_message = Message(
                role="assistant", content=f"Task {task.id} blocked: {error}"
            )
            messages = messages + (final_message,)
            trace = trace + (
                AgentTraceStep(
                    step=step,
                    event="task",
                    summary=f"blocked {task.title}: {error}",
                    task_id=task.id,
                    task_status="blocked",
                    is_error=True,
                ),
            )
            break

        if final_message is None:
            final_message = Message(
                role="assistant", content="No executable tasks remain."
            )
            messages = messages + (final_message,)

        session_store.save(
            session_id,
            replace(
                session_store.load(session_id),
                messages=messages,
                task_plan=task_plan,
                context_state=context_state,
            ),
        )
        return RunResult(
            final_message=final_message,
            messages=messages,
            trace=trace,
            task_plan=task_plan,
            memory_context=memory_context,
        )

    def _select_task_plan(
        self,
        *,
        existing_task_plan: TaskPlan | None,
        planner: Planner,
        user_input: str,
        history: tuple[Message, ...],
    ) -> TaskPlan:
        if existing_task_plan is not None and any(
            task.status != "completed" for task in existing_task_plan.tasks
        ):
            return existing_task_plan
        return planner.create_plan(user_input=user_input, history=history)

    def _run_message_loop(
        self,
        *,
        session_id: str,
        user_input: str,
        history: tuple[Message, ...],
        messages: tuple[Message, ...],
        model_client: ModelClient,
        registry: ToolRegistry,
        session_store: SessionStore,
        workspace_root: Path,
        max_steps: int,
        repository_context_builder: RepositoryContextBuilderProtocol | None,
        enable_repository_context: bool,
        memory_context: MemoryContext | None,
        context_manager: ContextManagerProtocol | None,
        stream_callback: Callable[[str], None] | None,
        notification_callback: NotificationCallback | None,
        skill_registry: SkillRegistry | None,
        skill_preprocessor: SkillPromptPreprocessor | None,
        permission_policy: PermissionPolicy | None,
        approval_callback: ApprovalCallback | None,
        system_prefix_messages: tuple[Message, ...],
    ) -> RunResult:
        context_state = session_store.load(session_id).context_state
        model_messages, context_state = self._build_model_messages(
            history=history,
            messages=messages,
            user_input=user_input,
            workspace_root=workspace_root,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
            memory_context=memory_context,
            skill_registry=skill_registry,
            task_plan=None,
            existing_context_state=context_state,
            context_manager=context_manager,
            system_prefix_messages=system_prefix_messages,
        )
        trace: tuple[AgentTraceStep, ...] = ()
        skill_calls_used = 0

        for step in range(1, max_steps + 1):
            response = model_client.complete(
                messages=model_messages,
                tools=registry.tools,
                stream_callback=stream_callback,
            )
            if isinstance(response, Message):
                final_messages = messages + (response,)
                session_store.save(
                    session_id,
                    replace(
                        session_store.load(session_id),
                        messages=final_messages,
                        context_state=context_state,
                    ),
                )
                trace = trace + (
                    AgentTraceStep(
                        step=step,
                        event="assistant",
                        summary=response.content,
                    ),
                )
                return RunResult(
                    final_message=response,
                    messages=final_messages,
                    trace=trace,
                    memory_context=memory_context,
                )

            if isinstance(response, SkillCall):
                messages, model_messages, trace = self._apply_skill_call(
                    response=response,
                    messages=messages,
                    model_messages=model_messages,
                    trace=trace,
                    step=step,
                    skill_calls_used=skill_calls_used,
                    skill_registry=skill_registry,
                    skill_preprocessor=skill_preprocessor,
                    notification_callback=notification_callback,
                    permission_policy=permission_policy,
                    approval_callback=approval_callback,
                )
                model_messages, context_state = self._build_model_messages(
                    history=history,
                    messages=messages,
                    user_input=user_input,
                    workspace_root=workspace_root,
                    repository_context_builder=repository_context_builder,
                    enable_repository_context=enable_repository_context,
                    memory_context=memory_context,
                    skill_registry=skill_registry,
                    task_plan=None,
                    existing_context_state=context_state,
                    context_manager=context_manager,
                    system_prefix_messages=system_prefix_messages,
                )
                skill_calls_used += 1
                continue

            executed_tool_calls, tool_results, tool_messages = self._run_tool_calls(
                response=response,
                registry=registry,
                workspace_root=workspace_root,
                permission_policy=permission_policy,
                approval_callback=approval_callback,
            )
            assistant_tool_message = Message(
                role="assistant", content="", tool_calls=executed_tool_calls
            )
            messages = messages + (assistant_tool_message, *tool_messages)
            model_messages, context_state = self._build_model_messages(
                history=history,
                messages=messages,
                user_input=user_input,
                workspace_root=workspace_root,
                repository_context_builder=repository_context_builder,
                enable_repository_context=enable_repository_context,
                memory_context=memory_context,
                skill_registry=skill_registry,
                task_plan=None,
                existing_context_state=context_state,
                context_manager=context_manager,
                system_prefix_messages=system_prefix_messages,
            )
            trace = trace + tuple(
                AgentTraceStep(
                    step=step,
                    event="tool",
                    summary=tool_result.content,
                    tool_name=tool_result.name,
                    is_error=tool_result.is_error,
                    permission_decision=(
                        str(tool_result.data.get("decision"))
                        if tool_result.data is not None
                        and "decision" in tool_result.data
                        else None
                    ),
                    reason_code=(
                        str(tool_result.data.get("reason_code"))
                        if tool_result.data is not None
                        and "reason_code" in tool_result.data
                        else None
                    ),
                )
                for tool_result in tool_results
            )
            if tool_results and tool_results[-1].is_error:
                final_message = Message(
                    role="assistant", content=tool_results[-1].content
                )
                final_messages = messages + (final_message,)
                session_store.save(
                    session_id,
                    replace(
                        session_store.load(session_id),
                        messages=final_messages,
                        context_state=context_state,
                    ),
                )
                return RunResult(
                    final_message=final_message,
                    messages=final_messages,
                    trace=trace,
                    memory_context=memory_context,
                )

        raise RuntimeLimitError(max_steps)

    def _run_task(
        self,
        *,
        task: Task,
        task_plan: TaskPlan,
        user_input: str,
        history: tuple[Message, ...],
        messages: tuple[Message, ...],
        model_client: ModelClient,
        registry: ToolRegistry,
        workspace_root: Path,
        max_steps: int,
        start_step: int,
        repository_context_builder: RepositoryContextBuilderProtocol | None,
        enable_repository_context: bool,
        memory_context: MemoryContext | None,
        context_manager: ContextManagerProtocol | None,
        stream_callback: Callable[[str], None] | None,
        notification_callback: NotificationCallback | None,
        skill_registry: SkillRegistry | None,
        skill_preprocessor: SkillPromptPreprocessor | None,
        permission_policy: PermissionPolicy | None,
        approval_callback: ApprovalCallback | None,
        existing_context_state: ContextManagementState | None,
        system_prefix_messages: tuple[Message, ...],
    ) -> _TaskRunResult:
        task_context_message = self._task_context_message(
            task=task, task_plan=task_plan
        )
        model_messages, context_state = self._build_model_messages(
            history=history,
            messages=messages,
            user_input=user_input,
            workspace_root=workspace_root,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
            memory_context=memory_context,
            skill_registry=skill_registry,
            task_plan=task_plan,
            existing_context_state=existing_context_state,
            context_manager=context_manager,
            prefix_messages=(task_context_message,),
            system_prefix_messages=system_prefix_messages,
        )
        trace: tuple[AgentTraceStep, ...] = ()
        step = start_step
        task_step = 0
        skill_calls_used = 0

        while task_step < max_steps:
            response = model_client.complete(
                messages=model_messages,
                tools=registry.tools,
                stream_callback=stream_callback,
            )
            if isinstance(response, Message):
                final_messages = messages + (response,)
                trace = trace + (
                    AgentTraceStep(
                        step=step,
                        event="assistant",
                        summary=response.content,
                        task_id=task.id,
                    ),
                )
                return _TaskRunResult(
                    messages=final_messages,
                    trace=trace,
                    next_step=step + 1,
                    final_message=response,
                    error=None,
                    context_state=context_state,
                )

            if isinstance(response, SkillCall):
                messages, model_messages, trace = self._apply_skill_call(
                    response=response,
                    messages=messages,
                    model_messages=model_messages,
                    trace=trace,
                    step=step,
                    skill_calls_used=skill_calls_used,
                    skill_registry=skill_registry,
                    skill_preprocessor=skill_preprocessor,
                    notification_callback=notification_callback,
                    permission_policy=permission_policy,
                    approval_callback=approval_callback,
                    task_id=task.id,
                )
                model_messages, context_state = self._build_model_messages(
                    history=history,
                    messages=messages,
                    user_input=user_input,
                    workspace_root=workspace_root,
                    repository_context_builder=repository_context_builder,
                    enable_repository_context=enable_repository_context,
                    memory_context=memory_context,
                    skill_registry=skill_registry,
                    task_plan=task_plan,
                    existing_context_state=context_state,
                    context_manager=context_manager,
                    prefix_messages=(task_context_message,),
                    system_prefix_messages=system_prefix_messages,
                )
                step += 1
                task_step += 1
                skill_calls_used += 1
                continue

            executed_tool_calls, tool_results, tool_messages = self._run_tool_calls(
                response=response,
                registry=registry,
                workspace_root=workspace_root,
                permission_policy=permission_policy,
                approval_callback=approval_callback,
            )
            assistant_tool_message = Message(
                role="assistant", content="", tool_calls=executed_tool_calls
            )
            messages = messages + (assistant_tool_message, *tool_messages)
            model_messages, context_state = self._build_model_messages(
                history=history,
                messages=messages,
                user_input=user_input,
                workspace_root=workspace_root,
                repository_context_builder=repository_context_builder,
                enable_repository_context=enable_repository_context,
                memory_context=memory_context,
                skill_registry=skill_registry,
                task_plan=task_plan,
                existing_context_state=context_state,
                context_manager=context_manager,
                prefix_messages=(task_context_message,),
                system_prefix_messages=system_prefix_messages,
            )
            trace = trace + tuple(
                AgentTraceStep(
                    step=step,
                    event="tool",
                    summary=tool_result.content,
                    tool_name=tool_result.name,
                    is_error=tool_result.is_error,
                    task_id=task.id,
                    permission_decision=(
                        str(tool_result.data.get("decision"))
                        if tool_result.data is not None
                        and "decision" in tool_result.data
                        else None
                    ),
                    reason_code=(
                        str(tool_result.data.get("reason_code"))
                        if tool_result.data is not None
                        and "reason_code" in tool_result.data
                        else None
                    ),
                )
                for tool_result in tool_results
            )
            step += 1
            task_step += 1
            if tool_results and tool_results[-1].is_error:
                return _TaskRunResult(
                    messages=messages,
                    trace=trace,
                    next_step=step,
                    final_message=None,
                    error=tool_results[-1].content,
                    context_state=context_state,
                )

        raise RuntimeLimitError(max_steps)

    def _build_memory_context(
        self,
        *,
        memory_context_builder: MemoryContextBuilderProtocol | None,
        user_input: str,
    ) -> MemoryContext | None:
        if memory_context_builder is None:
            return None
        try:
            return memory_context_builder.build(user_input=user_input)
        except (AgentError, OSError, ValueError):
            LOGGER.warning("memory context build failed", exc_info=True)
            return None

    def _notify_memory_recall(
        self,
        *,
        memory_context: MemoryContext | None,
        notification_callback: NotificationCallback,
    ) -> None:
        if memory_context is None or not memory_context.relevant_files:
            return
        notification_callback("Memory recall:")
        for file in memory_context.relevant_files:
            notification_callback(f"  - {file.relative_path}")

    def _build_model_messages(
        self,
        *,
        history: tuple[Message, ...],
        messages: tuple[Message, ...],
        user_input: str,
        workspace_root: Path,
        repository_context_builder: RepositoryContextBuilderProtocol | None,
        enable_repository_context: bool,
        memory_context: MemoryContext | None,
        skill_registry: SkillRegistry | None,
        task_plan: TaskPlan | None,
        existing_context_state: ContextManagementState | None,
        context_manager: ContextManagerProtocol | None,
        prefix_messages: tuple[Message, ...] = (),
        system_prefix_messages: tuple[Message, ...] = (),
    ) -> tuple[tuple[Message, ...], ContextManagementState | None]:
        system_messages: tuple[Message, ...] = tuple(system_prefix_messages)
        if enable_repository_context and repository_context_builder is not None:
            repository_context = repository_context_builder.build(
                workspace_root=workspace_root,
                user_input=user_input,
                history=history,
            )
            if repository_context.rendered:
                system_messages = (
                    *system_messages,
                    Message(role="system", content=repository_context.rendered),
                )
        if memory_context is not None and memory_context.prompt.strip():
            system_messages = (
                *system_messages,
                Message(role="system", content=memory_context.prompt),
            )
        skill_catalog_message = self._build_skill_catalog_message(skill_registry)
        if skill_catalog_message is not None:
            system_messages = (*system_messages, skill_catalog_message)
        model_messages = (*prefix_messages, *system_messages, *messages)
        if context_manager is None:
            return model_messages, existing_context_state
        return context_manager.prepare_messages(
            messages=model_messages,
            task_plan=task_plan,
            existing_state=existing_context_state,
        )

    def _build_skill_catalog_message(
        self, skill_registry: SkillRegistry | None
    ) -> Message | None:
        if skill_registry is None:
            return None
        entries = skill_registry.catalog_entries()
        if not entries:
            return None
        lines = [
            "Available skills can be selected by returning JSON only in the form "
            '{"skill":{"name":"skill-name","arguments":"optional args"}} '
            "when a skill clearly matches the request.",
            "Only choose a skill when its when_to_use guidance strongly applies.",
            "Do not choose more than one skill per turn.",
            "Available skills:",
        ]
        for entry in entries:
            when_to_use = entry.when_to_use or ""
            lines.append(
                f"- {entry.name}: {entry.description}"
                + (f" | when_to_use: {when_to_use}" if when_to_use else "")
            )
        return Message(role="system", content="\n".join(lines))

    def _apply_skill_call(
        self,
        *,
        response: SkillCall,
        messages: tuple[Message, ...],
        model_messages: tuple[Message, ...],
        trace: tuple[AgentTraceStep, ...],
        step: int,
        skill_calls_used: int,
        skill_registry: SkillRegistry | None,
        skill_preprocessor: SkillPromptPreprocessor | None,
        notification_callback: NotificationCallback | None,
        permission_policy: PermissionPolicy | None,
        approval_callback: ApprovalCallback | None,
        task_id: str | None = None,
    ) -> tuple[tuple[Message, ...], tuple[Message, ...], tuple[AgentTraceStep, ...]]:
        if skill_calls_used >= MAX_SKILL_CALLS_PER_TURN:
            raise AgentError("model selected too many skills in one turn")
        if skill_registry is None or skill_preprocessor is None:
            raise AgentError("model selected a skill but skills are not configured")
        if permission_policy is not None and permission_policy.mode.value == "plan":
            raise AgentError("model selected a skill that is not allowed in plan mode")
        skill = skill_registry.get(response.name)
        if skill is None:
            raise AgentError(f"model selected unknown skill: {response.name}")
        if not skill.metadata.model_selectable:
            raise AgentError(f"model selected non-selectable skill: {response.name}")
        try:
            invocation = build_skill_invocation(
                command_name=response.name, raw_args=response.raw_args
            )
            expanded = skill_preprocessor.expand_invocation_body(invocation)
        except SkillError as error:
            raise AgentError(str(error)) from error
        if notification_callback is not None:
            notification_callback(f"正在调用 skill: {response.name}")
        skill_message = Message(
            role="system",
            content=f"Activated skill: {response.name}\n\n{expanded}",
        )
        updated_messages = messages + (skill_message,)
        updated_model_messages = model_messages + (skill_message,)
        updated_trace = trace + (
            AgentTraceStep(
                step=step,
                event="skill",
                summary=f"activated {response.name}",
                task_id=task_id,
            ),
        )
        return updated_messages, updated_model_messages, updated_trace

    def _run_tool_calls(
        self,
        *,
        response: tuple[ToolCall, ...],
        registry: ToolRegistry,
        workspace_root: Path,
        permission_policy: PermissionPolicy | None,
        approval_callback: ApprovalCallback | None,
    ) -> tuple[tuple[ToolCall, ...], tuple[ToolResult, ...], tuple[Message, ...]]:
        self._validate_tool_call_batch(response)
        executed_tool_calls: tuple[ToolCall, ...] = ()
        tool_results: tuple[ToolResult, ...] = ()
        tool_messages: tuple[Message, ...] = ()
        for tool_call in response:
            tool_result = self._run_tool_call(
                tool_call=tool_call,
                registry=registry,
                workspace_root=workspace_root,
                permission_policy=permission_policy,
                approval_callback=approval_callback,
            )
            executed_tool_calls = (*executed_tool_calls, tool_call)
            tool_results = (*tool_results, tool_result)
            tool_messages = (
                *tool_messages,
                Message(
                    role="tool",
                    content=self._format_tool_message(tool_result),
                    tool_call_id=tool_call.call_id,
                ),
            )
            if tool_result.is_error:
                break
        return executed_tool_calls, tool_results, tool_messages

    def _run_tool_call(
        self,
        *,
        tool_call: ToolCall,
        registry: ToolRegistry,
        workspace_root: Path,
        permission_policy: PermissionPolicy | None,
        approval_callback: ApprovalCallback | None,
    ) -> ToolResult:
        tool = registry.get_tool(tool_call.name)
        if tool is None:
            return registry.invoke(tool_call=tool_call, workspace_root=workspace_root)
        if permission_policy is None:
            return registry.invoke(tool_call=tool_call, workspace_root=workspace_root)

        outcome = permission_policy.evaluate(
            PermissionRequest(
                tool_name=tool.name,
                tool_category=tool.permission_category,
                arguments=tool_call.arguments,
                workspace_root=workspace_root,
                is_read_only=tool.is_read_only,
            )
        )
        if outcome.decision == PermissionDecision.ALLOW:
            return registry.invoke(tool_call=tool_call, workspace_root=workspace_root)
        if outcome.decision == PermissionDecision.ASK:
            if approval_callback is None:
                return ToolResult(
                    name=tool.name,
                    content=outcome.reason,
                    is_error=True,
                    error_code="permission_required",
                    data={
                        "decision": outcome.decision.value,
                        "reason_code": outcome.reason_code,
                        "matched_rule": outcome.matched_rule,
                    },
                )
            approved = approval_callback(f"{tool.name}: {outcome.reason}")
            if approved:
                return registry.invoke(
                    tool_call=tool_call, workspace_root=workspace_root
                )

        return ToolResult(
            name=tool.name,
            content=outcome.reason,
            is_error=True,
            error_code="permission_denied",
            data={
                "decision": outcome.decision.value,
                "reason_code": outcome.reason_code,
                "matched_rule": outcome.matched_rule,
            },
        )

    def _format_tool_message(self, tool_result: ToolResult) -> str:
        return tool_result.to_message_content()

    def _validate_tool_call_batch(self, tool_calls: tuple[ToolCall, ...]) -> None:
        if not tool_calls:
            raise AgentError("model response tool_calls must be a non-empty list")
        if len(tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE:
            raise AgentError("model response has too many tool calls")
        call_ids = tuple(tool_call.call_id for tool_call in tool_calls)
        if any(call_id is None or not call_id for call_id in call_ids):
            raise AgentError("model response tool call missing id")
        if len(call_ids) != len(set(call_ids)):
            raise AgentError("model response tool call ids must be unique")

    def _task_context_message(self, *, task: Task, task_plan: TaskPlan) -> Message:
        completed = ", ".join(
            item.title for item in task_plan.tasks if item.status == "completed"
        )
        remaining = ", ".join(
            item.title
            for item in task_plan.tasks
            if item.status in {"pending", "blocked"}
        )
        return Message(
            role="system",
            content=(
                "Execute the current task. Do not explain this rule to the user when finished.\n"
                f"Current task: {task.id} - {task.title}\n"
                f"Description: {task.description}\n"
                f"Completed tasks: {completed or 'none'}\n"
                f"Remaining tasks: {remaining or 'none'}"
            ),
        )

    def _next_executable_task(self, task_plan: TaskPlan) -> Task | None:
        completed_task_ids = frozenset(
            task.id for task in task_plan.tasks if task.status == "completed"
        )
        for task in task_plan.tasks:
            if task.status == "pending" and all(
                dependency in completed_task_ids for dependency in task.dependencies
            ):
                return task
        return None

    def _refresh_blocked_statuses(self, task_plan: TaskPlan) -> TaskPlan:
        completed_task_ids = frozenset(
            task.id for task in task_plan.tasks if task.status == "completed"
        )
        return TaskPlan(
            tasks=tuple(
                (
                    replace(task, status="blocked")
                    if task.status == "pending"
                    and any(
                        dependency not in completed_task_ids
                        for dependency in task.dependencies
                    )
                    else (
                        replace(task, status="pending")
                        if task.status == "blocked"
                        and task.last_error is None
                        and all(
                            dependency in completed_task_ids
                            for dependency in task.dependencies
                        )
                        else task
                    )
                )
                for task in task_plan.tasks
            )
        )

    def _mark_task_status(
        self,
        task_plan: TaskPlan,
        task_id: str,
        status: str,
        *,
        last_error: str | None = None,
        attempts_increment: bool = False,
    ) -> TaskPlan:
        return TaskPlan(
            tasks=tuple(
                (
                    replace(
                        task,
                        status=status,  # type: ignore[arg-type]
                        last_error=(
                            last_error if last_error is not None else task.last_error
                        ),
                        attempts=(
                            task.attempts + 1 if attempts_increment else task.attempts
                        ),
                    )
                    if task.id == task_id
                    else task
                )
                for task in task_plan.tasks
            )
        )

    def _require_task(self, task_plan: TaskPlan, task_id: str) -> Task:
        for task in task_plan.tasks:
            if task.id == task_id:
                return task
        raise RuntimeError(f"missing task: {task_id}")


class _TaskRunResult:
    def __init__(
        self,
        *,
        messages: tuple[Message, ...],
        trace: tuple[AgentTraceStep, ...],
        next_step: int,
        final_message: Message | None,
        error: str | None,
        context_state: ContextManagementState | None,
    ) -> None:
        self.messages = messages
        self.trace = trace
        self.next_step = next_step
        self.final_message = final_message
        self.error = error
        self.context_state = context_state
