from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import typer

from project_agent import __version__
from project_agent.config import Settings, load_settings
from project_agent.core.interfaces import (
    MemoryContextBuilderProtocol,
    ModelClient,
    RepositoryContextBuilderProtocol,
    Tool,
)
from project_agent.core.types import (
    AgentTraceStep,
    MemoryContext,
    Message,
    MultiAgentRunResult,
    MultiAgentTraceStep,
    RunResult,
    TaskPlan,
)
from project_agent.errors import AgentError, map_exception_to_exit_code
from project_agent.logging import configure_logging
from project_agent.runtime.agent import AgentRuntime
from project_agent.runtime.context import RepositoryContextBuilder
from project_agent.runtime.context_management import (
    AutoCompactionPolicy,
    CompactionSummaryBuilder,
    ContextManager,
    HeuristicTokenEstimator,
    MicroCompactor,
)
from project_agent.runtime.mcp import build_github_mcp_config, build_mcp_tools
from project_agent.runtime.memory import (
    FileMemoryStore,
    MemoryContextBuilder,
    ModelMemoryRecall,
)
from project_agent.runtime.model_clients import (
    MockModelClient,
    OpenAICompatibleModelClient,
)
from project_agent.runtime.multi_agent import MultiAgentOrchestrator
from project_agent.runtime.multi_agent_tools import SubagentTool
from project_agent.runtime.permissions import PermissionPolicy
from project_agent.runtime.permissions.policy import load_permission_rules
from project_agent.runtime.permissions.types import PermissionRule
from project_agent.runtime.planner import LLMPlanner
from project_agent.runtime.session_store import FileSessionStore
from project_agent.runtime.tool_error_repair import SubagentToolErrorRepairer
from project_agent.runtime.tools import EchoTool, build_default_tools
from project_agent.skills import (
    SkillPromptPreprocessor,
    SkillRegistry,
    SkillRuntimeSettings,
    build_skill_invocation,
    load_skills,
)

CONFIG_OPTION = typer.Option(
    None,
    "--config",
    exists=True,
    file_okay=True,
    dir_okay=False,
)
WORKSPACE_ROOT_OPTION = typer.Option(None, "--workspace-root")
LOG_LEVEL_OPTION = typer.Option(None, "--log-level")
DEFAULT_MODEL_OPTION = typer.Option(None, "--default-model")
ENVIRONMENT_OPTION = typer.Option(None, "--environment")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x1b]")

app = typer.Typer(help="Project Agent CLI.")
mcp_app = typer.Typer(help="Manage MCP servers.")
app.add_typer(mcp_app, name="mcp")


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = CONFIG_OPTION,
    workspace_root: Path | None = WORKSPACE_ROOT_OPTION,
    log_level: str | None = LOG_LEVEL_OPTION,
    default_model: str | None = DEFAULT_MODEL_OPTION,
    environment: str | None = ENVIRONMENT_OPTION,
) -> None:
    overrides = {
        key: value
        for key, value in {
            "workspace_root": str(workspace_root) if workspace_root else None,
            "log_level": log_level,
            "default_model": default_model,
            "environment": environment,
        }.items()
        if value is not None
    }
    settings = load_settings(config_path=config, overrides=overrides)
    configure_logging(settings.log_level)
    ctx.obj = settings


@app.command()
def doctor(ctx: typer.Context) -> None:
    settings = _require_settings(ctx.obj)
    typer.echo(f"workspace_root={settings.workspace_root}")
    typer.echo(f"log_level={settings.log_level}")
    typer.echo(f"default_model={settings.default_model}")
    typer.echo(f"model_base_url={settings.model_base_url or ''}")
    typer.echo(f"model_api_key_configured={settings.model_api_key is not None}")
    typer.echo(f"prompt_cache={settings.prompt_cache}")
    typer.echo(f"environment={settings.environment}")
    typer.echo(f"memory_enabled={settings.memory_enabled}")
    typer.echo(f"memory_dir={settings.memory_dir}")
    typer.echo(f"multi_agent_enabled={settings.multi_agent_enabled}")
    typer.echo(f"coordinator_enabled={settings.coordinator_enabled}")
    typer.echo(f"max_subagents_per_turn={settings.max_subagents_per_turn}")
    typer.echo(f"max_subagent_steps={settings.max_subagent_steps}")
    typer.echo(f"max_worker_result_chars={settings.max_worker_result_chars}")
    typer.echo(f"multi_agent_strict_task_specs={settings.multi_agent_strict_task_specs}")
    typer.echo(f"mcp_enabled={settings.mcp_enabled}")
    typer.echo(f"mcp_config_file={settings.mcp_config_file}")
    typer.echo("multi_agent_roles=explore,plan,worker,verification,generalPurpose")
    typer.echo("recursive_subagents_supported=False")


@app.command()
def version() -> None:
    typer.echo(__version__)


@mcp_app.command("install-github")
def mcp_install_github(ctx: typer.Context, force: bool = typer.Option(False, "--force")) -> None:
    settings = _require_settings(ctx.obj)
    config_path = settings.mcp_config_file
    if config_path.exists() and not force:
        raise AgentError(f"MCP config already exists: {config_path}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(build_github_mcp_config(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"github MCP server configured at {config_path}")


@app.command()
def run(
    ctx: typer.Context,
    prompt: str | None = typer.Option(None, "--prompt"),
    session_id: str | None = typer.Option(None, "--session-id"),
    trace: bool = typer.Option(False, "--trace/--no-trace"),
    stream: bool | None = typer.Option(None, "--stream/--no-stream"),
    max_steps: int | None = typer.Option(None, "--max-steps"),
    multi_agent: bool | None = typer.Option(None, "--multi-agent/--no-multi-agent"),
    coordinator: bool | None = typer.Option(None, "--coordinator/--no-coordinator"),
    max_subagents: int | None = typer.Option(None, "--max-subagents"),
    max_subagent_steps: int | None = typer.Option(None, "--max-subagent-steps"),
) -> None:
    settings = _require_settings(ctx.obj)
    runtime = AgentRuntime()
    model_client = _build_model_client(settings)
    session_store = FileSessionStore(settings.session_store_dir)
    tools: list[Tool] = [
        EchoTool(),
        *build_default_tools(
            max_file_read_chars=settings.max_file_read_chars,
            command_timeout_seconds=settings.command_timeout_seconds,
            max_command_output_chars=settings.max_command_output_chars,
        ),
    ]
    if settings.mcp_enabled:
        tools.extend(
            build_mcp_tools(
                config_path=settings.mcp_config_file,
                request_timeout_seconds=settings.mcp_request_timeout_seconds,
                max_description_chars=settings.mcp_max_description_chars,
            )
        )
    repository_context_builder = RepositoryContextBuilder(
        max_repository_context_chars=settings.max_repository_context_chars,
        max_git_diff_chars=settings.max_git_diff_chars,
        max_rule_file_chars=settings.max_rule_file_chars,
        max_relevant_files=settings.max_relevant_files,
        max_relevant_file_chars=settings.max_relevant_file_chars,
        recent_commits_count=settings.recent_commits_count,
        context_command_timeout_seconds=settings.context_command_timeout_seconds,
    )
    skill_registry = _build_skill_registry(settings)
    permission_policy = _build_permission_policy(settings)
    skill_preprocessor = SkillPromptPreprocessor(
        registry=skill_registry,
        workspace_root=settings.workspace_root,
        max_composition_depth=settings.skills_max_composition_depth,
        max_expansion_chars=settings.skills_max_expansion_chars,
        runtime_settings=SkillRuntimeSettings(
            allow_command_substitution=settings.skills_allow_command_substitution
        ),
    )
    memory_context_builder = _build_memory_context_builder(settings)
    context_manager = ContextManager(
        budget_estimator=HeuristicTokenEstimator(),
        micro_compactor=MicroCompactor(
            recent_tool_results_keep=settings.context_recent_tool_results_keep,
            tool_result_preview_chars=settings.context_tool_result_preview_chars,
        ),
        auto_compaction_policy=AutoCompactionPolicy(
            trigger_fill_ratio=settings.context_trigger_fill_ratio,
            recover_fill_ratio=settings.context_recover_fill_ratio,
            circuit_breaker_failures=settings.context_circuit_breaker_failures,
        ),
        summary_builder=CompactionSummaryBuilder(
            profile=settings.context_profile,
            version=settings.context_profile_version,
            max_summary_tokens=settings.context_summary_max_tokens,
        ),
        context_window_tokens=settings.context_window_tokens,
        profile=settings.context_profile,
        version=settings.context_profile_version,
        enable_auto_compaction=settings.enable_auto_compaction,
        enable_full_compaction=settings.enable_full_compaction,
    )
    active_session_id = session_id or uuid4().hex
    active_max_steps = max_steps or settings.max_steps
    should_stream = settings.stream_output if stream is None else stream
    active_multi_agent = settings.multi_agent_enabled if multi_agent is None else multi_agent
    active_coordinator = settings.coordinator_enabled if coordinator is None else coordinator
    active_max_subagents = max_subagents or settings.max_subagents_per_turn
    active_max_subagent_steps = max_subagent_steps or settings.max_subagent_steps
    orchestrator = MultiAgentOrchestrator(runtime=runtime)

    if prompt is not None:
        _run_once(
            runtime=runtime,
            model_client=model_client,
            session_store=session_store,
            tools=tools,
            settings=settings,
            session_id=active_session_id,
            user_input=prompt,
            show_trace=trace,
            stream_output=should_stream,
            max_steps=active_max_steps,
            repository_context_builder=repository_context_builder,
            enable_repository_context=settings.enable_repository_context,
            memory_context_builder=memory_context_builder,
            skill_registry=skill_registry,
            skill_preprocessor=skill_preprocessor,
            permission_policy=permission_policy,
            context_manager=context_manager,
            interactive_approval=False,
            multi_agent_enabled=active_multi_agent,
            coordinator_enabled=active_coordinator,
            max_subagents=active_max_subagents,
            max_subagent_steps=active_max_subagent_steps,
            orchestrator=orchestrator,
        )
        return

    while True:
        user_input = typer.prompt("You")
        if user_input.strip() == "/exit":
            typer.echo("Exiting interactive mode.")
            return
        _run_once(
            runtime=runtime,
            model_client=model_client,
            session_store=session_store,
            tools=tools,
            settings=settings,
            session_id=active_session_id,
            user_input=user_input,
            show_trace=trace,
            stream_output=should_stream,
            max_steps=active_max_steps,
            repository_context_builder=repository_context_builder,
            enable_repository_context=settings.enable_repository_context,
            memory_context_builder=memory_context_builder,
            skill_registry=skill_registry,
            skill_preprocessor=skill_preprocessor,
            permission_policy=permission_policy,
            context_manager=context_manager,
            interactive_approval=True,
            multi_agent_enabled=active_multi_agent,
            coordinator_enabled=active_coordinator,
            max_subagents=active_max_subagents,
            max_subagent_steps=active_max_subagent_steps,
            orchestrator=orchestrator,
        )


def _parse_command(text: str) -> tuple[str | None, str]:
    text = text.strip()
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        return parts[0], parts[1] if len(parts) > 1 else ""
    return None, text


def _format_skill_catalog_for_planner(skill_registry: SkillRegistry) -> str | None:
    entries = skill_registry.catalog_entries()
    if not entries:
        return None
    return "\n".join(
        f"- {entry.name}: {entry.description}"
        + (f" | when_to_use: {entry.when_to_use}" if entry.when_to_use else "")
        for entry in entries
    )


def _run_once(
    *,
    runtime: AgentRuntime,
    model_client: ModelClient,
    session_store: FileSessionStore,
    tools: list[Tool],
    settings: Settings,
    session_id: str,
    user_input: str,
    show_trace: bool,
    stream_output: bool,
    max_steps: int,
    repository_context_builder: RepositoryContextBuilderProtocol,
    enable_repository_context: bool,
    memory_context_builder: MemoryContextBuilderProtocol | None,
    skill_registry: SkillRegistry,
    skill_preprocessor: SkillPromptPreprocessor,
    permission_policy: PermissionPolicy,
    context_manager: ContextManager,
    interactive_approval: bool,
    multi_agent_enabled: bool,
    coordinator_enabled: bool,
    max_subagents: int,
    max_subagent_steps: int,
    orchestrator: MultiAgentOrchestrator,
) -> None:
    import sys

    streamed_output: list[str] = []

    def stream_callback(char: str) -> None:
        streamed_output.append(char)
        sys.stdout.write(char)
        sys.stdout.flush()

    def notification_callback(message: str) -> None:
        sys.stdout.write(f"{_sanitize_cli_text(message)}\n")
        sys.stdout.flush()

    def approval_callback(message: str) -> bool:
        return typer.confirm(
            f"Approve action? {_sanitize_cli_text(message)}", default=False
        )

    cmd, actual_input = _parse_command(user_input)

    planner = None
    use_coordinator = coordinator_enabled
    if cmd == "/coordinator":
        use_coordinator = True
    elif cmd == "/plan-execute" and use_coordinator:
        typer.echo("coordinator mode cannot be combined with /plan-execute yet")
        return
    if cmd == "/plan-execute":
        planner = LLMPlanner(
            model_client=model_client,
            skill_catalog=_format_skill_catalog_for_planner(skill_registry),
        )
    elif cmd == "/coordinator":
        pass
    elif cmd is not None:
        skill = skill_registry.get(cmd.removeprefix("/"))
        if skill is None or not skill.metadata.user_invocable:
            typer.echo(f"Unknown command: {cmd}")
            return
        actual_input = skill_preprocessor.expand_invocation(
            build_skill_invocation(command_name=cmd, raw_args=actual_input)
        )

    tool_error_repairer = None
    if settings.tool_error_repair_enabled:
        tool_error_repairer = SubagentToolErrorRepairer(
            orchestrator=orchestrator,
            parent_session_id=session_id,
            model_client=model_client,
            tools=tools,
            session_store=session_store,
            max_steps=settings.tool_error_repair_max_steps,
            max_worker_result_chars=settings.tool_error_repair_max_worker_result_chars,
            repository_context_builder=repository_context_builder,
            enable_repository_context=False,
            memory_context_builder=None,
            context_manager=context_manager,
            notification_callback=notification_callback,
            skill_registry=skill_registry,
            skill_preprocessor=skill_preprocessor,
            permission_policy=permission_policy,
        )

    active_tools = tools
    if multi_agent_enabled or use_coordinator:
        active_tools = [
            *tools,
            SubagentTool(
                orchestrator=orchestrator,
                parent_session_id=session_id,
                model_client=model_client,
                tools=tools,
                session_store=session_store,
                workspace_root=settings.workspace_root,
                max_steps=max_subagent_steps,
                max_subagents=max_subagents,
                max_worker_result_chars=settings.max_worker_result_chars,
                repository_context_builder=repository_context_builder,
                enable_repository_context=enable_repository_context,
                memory_context_builder=memory_context_builder,
                context_manager=context_manager,
                notification_callback=notification_callback,
                skill_registry=skill_registry,
                skill_preprocessor=skill_preprocessor,
                permission_policy=permission_policy,
                approval_callback=approval_callback if interactive_approval else None,
                parent_user_input=actual_input,
                default_role="worker",
                strict_task_specs=settings.multi_agent_strict_task_specs,
                parent_depth=0,
            ),
        ]
    result: RunResult | MultiAgentRunResult
    if use_coordinator:
        result = orchestrator.run_coordinator_turn(
            session_id=session_id,
            user_input=actual_input,
            model_client=model_client,
            tools=active_tools,
            session_store=session_store,
            workspace_root=settings.workspace_root,
            max_steps=max_steps,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
            memory_context_builder=memory_context_builder,
            stream_callback=stream_callback if stream_output else None,
            notification_callback=notification_callback,
            skill_registry=skill_registry,
            skill_preprocessor=skill_preprocessor,
            permission_policy=permission_policy,
            approval_callback=approval_callback if interactive_approval else None,
            context_manager=context_manager,
        )
    else:
        result = runtime.run_turn(
            session_id=session_id,
            user_input=actual_input,
            model_client=model_client,
            tools=active_tools,
            session_store=session_store,
            workspace_root=settings.workspace_root,
            max_steps=max_steps,
            repository_context_builder=repository_context_builder,
            enable_repository_context=enable_repository_context,
            memory_context_builder=memory_context_builder,
            planner=planner,
            stream_callback=stream_callback if stream_output else None,
            notification_callback=notification_callback,
            skill_registry=skill_registry,
            skill_preprocessor=skill_preprocessor,
            permission_policy=permission_policy,
            approval_callback=approval_callback if interactive_approval else None,
            context_manager=context_manager,
            tool_error_repairer=tool_error_repairer,
        )
    if stream_output:
        if not streamed_output and result.final_message.content:
            sys.stdout.write(_sanitize_final_output(result.final_message.content))
        sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        typer.echo(_sanitize_final_output(result.final_message.content))
    _echo_task_progress(result.task_plan)
    if show_trace:
        _echo_trace(result.trace)


def _echo_streamed_output(message: Message) -> None:
    typer.echo(_sanitize_final_output(message.content))


def _echo_memory_recall(memory_context: MemoryContext | None) -> None:
    if memory_context is None or not memory_context.relevant_files:
        return
    typer.echo("Memory recall:")
    for file in memory_context.relevant_files:
        typer.echo(f"  - {_sanitize_cli_text(file.relative_path)}")


def _echo_task_progress(task_plan: TaskPlan | None) -> None:
    if task_plan is None:
        return
    typer.echo("Tasks:")
    for task in task_plan.tasks:
        typer.echo(f"  - {task.status} {task.id}: {_sanitize_cli_text(task.title)}")


def _echo_trace(trace: tuple[AgentTraceStep | MultiAgentTraceStep, ...]) -> None:
    for step in trace:
        if (
            isinstance(step, AgentTraceStep)
            and step.event == "task"
            and step.task_id is not None
            and step.task_status is not None
        ):
            status = "error" if step.is_error else "ok"
            typer.echo(
                f"[step {step.step}] task {step.task_id} "
                f"{step.task_status} {status}: {_sanitize_cli_text(step.summary)}"
            )
        if step.event == "tool" and isinstance(step, AgentTraceStep) and step.tool_name is not None:
            status = "error" if step.is_error else "ok"
            typer.echo(
                f"[step {step.step}] tool {step.tool_name} {status}: "
                f"{_sanitize_cli_text(step.summary)}"
            )
        if step.event == "agent" and isinstance(step, MultiAgentTraceStep):
            status = "error" if step.is_error else "ok"
            typer.echo(
                f"[step {step.step}] agent {step.agent_id or ''} "
                f"{step.status or ''} {status}: {_sanitize_cli_text(step.summary)}"
            )


def _sanitize_final_output(value: str) -> str:
    return CONTROL_CHAR_PATTERN.sub("?", value).replace("\r", "\\r")


def _sanitize_cli_text(value: str) -> str:
    return (
        CONTROL_CHAR_PATTERN.sub("?", value).replace("\r", "\\r").replace("\n", "\\n")
    )


def _build_model_client(settings: Settings) -> ModelClient:
    if settings.model_base_url is None and settings.model_api_key is None:
        return MockModelClient()
    if settings.model_base_url is None:
        raise AgentError("model_base_url is required when PROJECT_AGENT_API_KEY is set")
    if settings.model_api_key is None:
        raise AgentError("PROJECT_AGENT_API_KEY is required when model_base_url is set")
    return OpenAICompatibleModelClient(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.default_model,
        prompt_cache=settings.prompt_cache,
    )


def _build_memory_context_builder(settings: Settings) -> MemoryContextBuilder | None:
    if not settings.memory_enabled:
        return None
    return MemoryContextBuilder(
        store=FileMemoryStore(memory_dir=settings.memory_dir),
        recall=ModelMemoryRecall(model_client=_build_model_client(settings)),
        entrypoint_max_lines=settings.memory_entrypoint_max_lines,
        entrypoint_max_bytes=settings.memory_entrypoint_max_bytes,
        max_relevant_files=settings.memory_max_relevant_files,
        max_relevant_file_chars=settings.memory_max_relevant_file_chars,
        max_manifest_files=settings.memory_max_manifest_files,
    )


def _build_skill_registry(settings: Settings) -> SkillRegistry:
    builtin_root = None
    if settings.skills_enabled and settings.skills_builtin_enabled:
        builtin_root = Path(__file__).resolve().parent / "skills" / "builtin"
    project_root = settings.project_skills_dir if settings.skills_enabled else None
    user_root = settings.user_skills_dir if settings.skills_enabled else None
    skills = load_skills(
        builtin_root=builtin_root, user_root=user_root, project_root=project_root
    )
    return SkillRegistry(skills)


def _build_permission_policy(settings: Settings) -> PermissionPolicy:
    rules: tuple[PermissionRule, ...] = ()
    if settings.permission_rules_file is not None:
        rules = load_permission_rules(settings.permission_rules_file)
    return PermissionPolicy(mode=settings.permission_mode, rules=rules)


def _require_settings(obj: object) -> Settings:
    if not isinstance(obj, Settings):
        raise AgentError("settings were not initialized")
    return obj


def main_entry() -> int:
    try:
        app()
    except AgentError as error:
        typer.echo(f"Error: {_sanitize_cli_text(str(error))}", err=True)
        return map_exception_to_exit_code(error)
    except Exception as error:  # pragma: no cover
        typer.echo(f"Error: unexpected failure: {type(error).__name__}", err=True)
        return map_exception_to_exit_code(error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
