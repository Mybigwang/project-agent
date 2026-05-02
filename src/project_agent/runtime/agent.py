from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from project_agent.core.interfaces import (
    ModelClient,
    RepositoryContextBuilderProtocol,
    SessionStore,
    Tool,
)
from project_agent.core.types import AgentTraceStep, Message, RunResult, ToolCall, ToolResult
from project_agent.errors import RuntimeLimitError
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
    ) -> RunResult:
        history = tuple(session_store.load(session_id))
        messages = history + (Message(role="user", content=user_input),)
        model_messages = self._build_model_messages(
            history=history,
            messages=messages,
            user_input=user_input,
            workspace_root=workspace_root,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
        )
        trace: tuple[AgentTraceStep, ...] = ()
        registry = ToolRegistry(tools)

        for step in range(1, max_steps + 1):
            response = model_client.complete(messages=model_messages, tools=registry.tools)
            if isinstance(response, Message):
                final_messages = messages + (response,)
                session_store.save(session_id, final_messages)
                trace = trace + (
                    AgentTraceStep(
                        step=step,
                        event="assistant",
                        summary=response.content,
                    ),
                )
                return RunResult(final_message=response, messages=final_messages, trace=trace)

            tool_result = self._run_tool_call(
                tool_call=response,
                registry=registry,
                workspace_root=workspace_root,
            )
            assistant_tool_message = Message(
                role="assistant",
                content="",
                tool_calls=(response,),
            )
            tool_message = Message(
                role="tool",
                content=self._format_tool_message(tool_result),
                tool_call_id=response.call_id,
            )
            messages = messages + (assistant_tool_message, tool_message)
            model_messages = model_messages + (assistant_tool_message, tool_message)
            trace = trace + (
                AgentTraceStep(
                    step=step,
                    event="tool",
                    summary=tool_result.content,
                    tool_name=tool_result.name,
                    is_error=tool_result.is_error,
                ),
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
