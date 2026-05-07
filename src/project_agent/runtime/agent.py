from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from project_agent.core.interfaces import (
    ModelClient,
    Planner,
    RepositoryContextBuilderProtocol,
    SessionStore,
    Tool,
)
from project_agent.core.types import (
    AgentTraceStep,
    Message,
    RunResult,
    SessionState,
    Task,
    TaskPlan,
    ToolCall,
    ToolResult,
)
from project_agent.errors import AgentError, RuntimeLimitError
from project_agent.runtime.model_clients import MAX_TOOL_CALLS_PER_RESPONSE
from project_agent.runtime.tool_registry import ToolRegistry


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
        planner: Planner | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> RunResult:
        state = session_store.load(session_id)
        history = state.messages
        messages = history + (Message(role="user", content=user_input),)
        registry = ToolRegistry(tools)
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
                stream_callback=stream_callback,
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
                stream_callback=stream_callback,
            )
            messages = task_result.messages
            trace = trace + task_result.trace
            step = task_result.next_step
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
                task_plan=self._mark_task_status(task_plan, task.id, "blocked", last_error=error),
                failed_task_id=task.id,
                error=error,
            )
            final_message = Message(role="assistant", content=f"Task {task.id} blocked: {error}")
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
            final_message = Message(role="assistant", content="No executable tasks remain.")
            messages = messages + (final_message,)

        session_store.save(session_id, SessionState(messages=messages, task_plan=task_plan))
        return RunResult(
            final_message=final_message, messages=messages, trace=trace, task_plan=task_plan
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
        stream_callback: Callable[[str], None] | None,
    ) -> RunResult:
        model_messages = self._build_model_messages(
            history=history,
            messages=messages,
            user_input=user_input,
            workspace_root=workspace_root,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
        )
        trace: tuple[AgentTraceStep, ...] = ()

        for step in range(1, max_steps + 1):
            response = model_client.complete(
                messages=model_messages, tools=registry.tools, stream_callback=stream_callback
            )
            if isinstance(response, Message):
                final_messages = messages + (response,)
                session_store.save(session_id, SessionState(messages=final_messages))
                trace = trace + (
                    AgentTraceStep(
                        step=step,
                        event="assistant",
                        summary=response.content,
                    ),
                )
                return RunResult(final_message=response, messages=final_messages, trace=trace)

            executed_tool_calls, tool_results, tool_messages = self._run_tool_calls(
                response=response,
                registry=registry,
                workspace_root=workspace_root,
            )
            assistant_tool_message = Message(
                role="assistant", content="", tool_calls=executed_tool_calls
            )
            messages = messages + (assistant_tool_message, *tool_messages)
            model_messages = model_messages + (assistant_tool_message, *tool_messages)
            trace = trace + tuple(
                AgentTraceStep(
                    step=step,
                    event="tool",
                    summary=tool_result.content,
                    tool_name=tool_result.name,
                    is_error=tool_result.is_error,
                )
                for tool_result in tool_results
            )
            if tool_results and tool_results[-1].is_error:
                final_message = Message(role="assistant", content=tool_results[-1].content)
                final_messages = messages + (final_message,)
                session_store.save(session_id, SessionState(messages=final_messages))
                return RunResult(
                    final_message=final_message,
                    messages=final_messages,
                    trace=trace,
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
        stream_callback: Callable[[str], None] | None,
    ) -> _TaskRunResult:
        model_messages = self._build_model_messages(
            history=history,
            messages=messages,
            user_input=user_input,
            workspace_root=workspace_root,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
        )
        model_messages = (
            self._task_context_message(task=task, task_plan=task_plan),
            *model_messages,
        )
        trace: tuple[AgentTraceStep, ...] = ()
        step = start_step
        task_step = 0

        while task_step < max_steps:
            response = model_client.complete(
                messages=model_messages, tools=registry.tools, stream_callback=stream_callback
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
                )

            executed_tool_calls, tool_results, tool_messages = self._run_tool_calls(
                response=response,
                registry=registry,
                workspace_root=workspace_root,
            )
            assistant_tool_message = Message(
                role="assistant", content="", tool_calls=executed_tool_calls
            )
            messages = messages + (assistant_tool_message, *tool_messages)
            model_messages = model_messages + (assistant_tool_message, *tool_messages)
            trace = trace + tuple(
                AgentTraceStep(
                    step=step,
                    event="tool",
                    summary=tool_result.content,
                    tool_name=tool_result.name,
                    is_error=tool_result.is_error,
                    task_id=task.id,
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
                )


        raise RuntimeLimitError(max_steps)

    def _build_model_messages(
        self,
        *,
        history: tuple[Message, ...],
        messages: tuple[Message, ...],
        user_input: str,
        workspace_root: Path,
        repository_context_builder: RepositoryContextBuilderProtocol | None,
        enable_repository_context: bool,
    ) -> tuple[Message, ...]:
        if not enable_repository_context or repository_context_builder is None:
            return messages
        repository_context = repository_context_builder.build(
            workspace_root=workspace_root,
            user_input=user_input,
            history=history,
        )
        if not repository_context.rendered:
            return messages
        return (Message(role="system", content=repository_context.rendered), *messages)

    def _run_tool_calls(
        self,
        *,
        response: tuple[ToolCall, ...],
        registry: ToolRegistry,
        workspace_root: Path,
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
    ) -> ToolResult:
        return registry.invoke(tool_call=tool_call, workspace_root=workspace_root)

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
        completed = ", ".join(item.title for item in task_plan.tasks if item.status == "completed")
        remaining = ", ".join(
            item.title for item in task_plan.tasks if item.status in {"pending", "blocked"}
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
                replace(task, status="blocked")
                if task.status == "pending"
                and any(dependency not in completed_task_ids for dependency in task.dependencies)
                else replace(task, status="pending")
                if task.status == "blocked"
                and task.last_error is None
                and all(dependency in completed_task_ids for dependency in task.dependencies)
                else task
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
                replace(
                    task,
                    status=status,  # type: ignore[arg-type]
                    last_error=last_error if last_error is not None else task.last_error,
                    attempts=task.attempts + 1 if attempts_increment else task.attempts,
                )
                if task.id == task_id
                else task
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
    ) -> None:
        self.messages = messages
        self.trace = trace
        self.next_step = next_step
        self.final_message = final_message
        self.error = error
