from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from project_agent.errors import ConfigurationError
from project_agent.runtime.permissions import PermissionMode

VALID_LOG_LEVELS = frozenset({"critical", "error", "warning", "info", "debug"})


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    log_level: str
    default_model: str
    model_base_url: str | None
    model_api_key: str | None
    environment: str
    session_store_dir: Path
    max_steps: int
    stream_output: bool
    command_timeout_seconds: float
    max_command_output_chars: int
    max_file_read_chars: int
    enable_repository_context: bool
    max_repository_context_chars: int
    max_git_diff_chars: int
    max_rule_file_chars: int
    max_relevant_files: int
    max_relevant_file_chars: int
    recent_commits_count: int
    context_command_timeout_seconds: float
    skills_enabled: bool
    skills_builtin_enabled: bool
    project_skills_dir: Path | None
    user_skills_dir: Path | None
    skills_allow_command_substitution: bool
    skills_max_composition_depth: int
    skills_max_expansion_chars: int
    permission_mode: PermissionMode
    permission_rules_file: Path | None
    context_window_tokens: int
    context_trigger_fill_ratio: float
    context_recover_fill_ratio: float
    context_circuit_breaker_failures: int
    context_recent_tool_results_keep: int
    context_tool_result_preview_chars: int
    context_summary_max_tokens: int
    context_profile: str
    context_profile_version: str
    enable_auto_compaction: bool
    enable_full_compaction: bool
    repository_context_max_tokens: int
    memory_enabled: bool
    memory_dir: Path
    memory_entrypoint_max_lines: int
    memory_entrypoint_max_bytes: int
    memory_max_relevant_files: int
    memory_max_relevant_file_chars: int
    memory_max_manifest_files: int
    multi_agent_enabled: bool
    coordinator_enabled: bool
    max_subagents_per_turn: int
    max_subagent_steps: int
    max_worker_result_chars: int
    allow_recursive_subagents: bool


def load_settings(
    *,
    config_path: Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Settings:
    config_values = _load_config_file(config_path) if config_path else {}
    override_values = dict(overrides or {})

    workspace_root = Path(
        override_values.get(
            "workspace_root",
            os.getenv("PROJECT_AGENT_WORKSPACE_ROOT", config_values.get("workspace_root", ".")),
        )
    ).resolve()
    log_level = override_values.get(
        "log_level",
        os.getenv("PROJECT_AGENT_LOG_LEVEL", config_values.get("log_level", "info")),
    ).lower()
    default_model = override_values.get(
        "default_model",
        os.getenv("PROJECT_AGENT_DEFAULT_MODEL", config_values.get("default_model", "mock-model")),
    )
    model_base_url = override_values.get(
        "model_base_url",
        os.getenv("PROJECT_AGENT_MODEL_BASE_URL", config_values.get("model_base_url", "")),
    )
    model_api_key = override_values.get(
        "model_api_key",
        os.getenv("PROJECT_AGENT_API_KEY", config_values.get("model_api_key", "")),
    )
    environment = override_values.get(
        "environment",
        os.getenv("PROJECT_AGENT_ENVIRONMENT", config_values.get("environment", "development")),
    )
    session_store_dir = Path(
        override_values.get(
            "session_store_dir",
            os.getenv(
                "PROJECT_AGENT_SESSION_STORE_DIR",
                config_values.get(
                    "session_store_dir", str(workspace_root / ".project_agent" / "sessions")
                ),
            ),
        )
    ).resolve()
    max_steps = int(
        override_values.get(
            "max_steps",
            os.getenv("PROJECT_AGENT_MAX_STEPS", config_values.get("max_steps", "24")),
        )
    )
    stream_output = _parse_bool(
        override_values.get(
            "stream_output",
            os.getenv("PROJECT_AGENT_STREAM_OUTPUT", config_values.get("stream_output", "false")),
        )
    )
    command_timeout_seconds = float(
        override_values.get(
            "command_timeout_seconds",
            os.getenv(
                "PROJECT_AGENT_COMMAND_TIMEOUT_SECONDS",
                config_values.get("command_timeout_seconds", "30"),
            ),
        )
    )
    max_command_output_chars = int(
        override_values.get(
            "max_command_output_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_COMMAND_OUTPUT_CHARS",
                config_values.get("max_command_output_chars", "4000"),
            ),
        )
    )
    max_file_read_chars = int(
        override_values.get(
            "max_file_read_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_FILE_READ_CHARS",
                config_values.get("max_file_read_chars", "12000"),
            ),
        )
    )
    enable_repository_context = _parse_bool(
        override_values.get(
            "enable_repository_context",
            os.getenv(
                "PROJECT_AGENT_ENABLE_REPOSITORY_CONTEXT",
                config_values.get("enable_repository_context", "true"),
            ),
        )
    )
    max_repository_context_chars = int(
        override_values.get(
            "max_repository_context_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_REPOSITORY_CONTEXT_CHARS",
                config_values.get("max_repository_context_chars", "20000"),
            ),
        )
    )
    max_git_diff_chars = int(
        override_values.get(
            "max_git_diff_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_GIT_DIFF_CHARS", config_values.get("max_git_diff_chars", "6000")
            ),
        )
    )
    max_rule_file_chars = int(
        override_values.get(
            "max_rule_file_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_RULE_FILE_CHARS",
                config_values.get("max_rule_file_chars", "6000"),
            ),
        )
    )
    max_relevant_files = int(
        override_values.get(
            "max_relevant_files",
            os.getenv(
                "PROJECT_AGENT_MAX_RELEVANT_FILES", config_values.get("max_relevant_files", "5")
            ),
        )
    )
    max_relevant_file_chars = int(
        override_values.get(
            "max_relevant_file_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_RELEVANT_FILE_CHARS",
                config_values.get("max_relevant_file_chars", "3000"),
            ),
        )
    )
    recent_commits_count = int(
        override_values.get(
            "recent_commits_count",
            os.getenv(
                "PROJECT_AGENT_RECENT_COMMITS_COUNT", config_values.get("recent_commits_count", "5")
            ),
        )
    )
    context_command_timeout_seconds = float(
        override_values.get(
            "context_command_timeout_seconds",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_COMMAND_TIMEOUT_SECONDS",
                config_values.get("context_command_timeout_seconds", "5"),
            ),
        )
    )
    skills_enabled = _parse_bool(
        override_values.get(
            "skills_enabled",
            os.getenv("PROJECT_AGENT_SKILLS_ENABLED", config_values.get("skills_enabled", "true")),
        )
    )
    skills_builtin_enabled = _parse_bool(
        override_values.get(
            "skills_builtin_enabled",
            os.getenv(
                "PROJECT_AGENT_SKILLS_BUILTIN_ENABLED",
                config_values.get("skills_builtin_enabled", "true"),
            ),
        )
    )
    project_skills_dir = _parse_optional_path(
        override_values.get(
            "project_skills_dir",
            os.getenv(
                "PROJECT_AGENT_PROJECT_SKILLS_DIR",
                config_values.get(
                    "project_skills_dir", str(workspace_root / ".project_agent" / "skills")
                ),
            ),
        ),
        workspace_root=workspace_root,
    )
    user_skills_dir = _parse_optional_path(
        override_values.get(
            "user_skills_dir",
            os.getenv("PROJECT_AGENT_USER_SKILLS_DIR", config_values.get("user_skills_dir", "")),
        ),
        workspace_root=workspace_root,
    )
    skills_allow_command_substitution = _parse_bool(
        override_values.get(
            "skills_allow_command_substitution",
            os.getenv(
                "PROJECT_AGENT_SKILLS_ALLOW_COMMAND_SUBSTITUTION",
                config_values.get("skills_allow_command_substitution", "false"),
            ),
        )
    )
    skills_max_composition_depth = int(
        override_values.get(
            "skills_max_composition_depth",
            os.getenv(
                "PROJECT_AGENT_SKILLS_MAX_COMPOSITION_DEPTH",
                config_values.get("skills_max_composition_depth", "3"),
            ),
        )
    )
    skills_max_expansion_chars = int(
        override_values.get(
            "skills_max_expansion_chars",
            os.getenv(
                "PROJECT_AGENT_SKILLS_MAX_EXPANSION_CHARS",
                config_values.get("skills_max_expansion_chars", "20000"),
            ),
        )
    )
    permission_mode = _parse_permission_mode(
        override_values.get(
            "permission_mode",
            os.getenv("PROJECT_AGENT_PERMISSION_MODE", config_values.get("permission_mode", "default")),
        )
    )
    permission_rules_file = _parse_optional_path(
        override_values.get(
            "permission_rules_file",
            os.getenv("PROJECT_AGENT_PERMISSION_RULES_FILE", config_values.get("permission_rules_file", "")),
        ),
        workspace_root=workspace_root,
    )
    context_window_tokens = int(
        override_values.get(
            "context_window_tokens",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_WINDOW_TOKENS",
                config_values.get("context_window_tokens", "200000"),
            ),
        )
    )
    context_trigger_fill_ratio = float(
        override_values.get(
            "context_trigger_fill_ratio",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_TRIGGER_FILL_RATIO",
                config_values.get("context_trigger_fill_ratio", "0.87"),
            ),
        )
    )
    context_recover_fill_ratio = float(
        override_values.get(
            "context_recover_fill_ratio",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_RECOVER_FILL_RATIO",
                config_values.get("context_recover_fill_ratio", "0.82"),
            ),
        )
    )
    context_circuit_breaker_failures = int(
        override_values.get(
            "context_circuit_breaker_failures",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_CIRCUIT_BREAKER_FAILURES",
                config_values.get("context_circuit_breaker_failures", "3"),
            ),
        )
    )
    context_recent_tool_results_keep = int(
        override_values.get(
            "context_recent_tool_results_keep",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_RECENT_TOOL_RESULTS_KEEP",
                config_values.get("context_recent_tool_results_keep", "5"),
            ),
        )
    )
    context_tool_result_preview_chars = int(
        override_values.get(
            "context_tool_result_preview_chars",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_TOOL_RESULT_PREVIEW_CHARS",
                config_values.get("context_tool_result_preview_chars", "400"),
            ),
        )
    )
    context_summary_max_tokens = int(
        override_values.get(
            "context_summary_max_tokens",
            os.getenv(
                "PROJECT_AGENT_CONTEXT_SUMMARY_MAX_TOKENS",
                config_values.get("context_summary_max_tokens", "4000"),
            ),
        )
    )
    context_profile = override_values.get(
        "context_profile",
        os.getenv("PROJECT_AGENT_CONTEXT_PROFILE", config_values.get("context_profile", "compact-default")),
    )
    context_profile_version = override_values.get(
        "context_profile_version",
        os.getenv(
            "PROJECT_AGENT_CONTEXT_PROFILE_VERSION",
            config_values.get("context_profile_version", "2026-05-12"),
        ),
    )
    enable_auto_compaction = _parse_bool(
        override_values.get(
            "enable_auto_compaction",
            os.getenv(
                "PROJECT_AGENT_ENABLE_AUTO_COMPACTION",
                config_values.get("enable_auto_compaction", "true"),
            ),
        )
    )
    enable_full_compaction = _parse_bool(
        override_values.get(
            "enable_full_compaction",
            os.getenv(
                "PROJECT_AGENT_ENABLE_FULL_COMPACTION",
                config_values.get("enable_full_compaction", "true"),
            ),
        )
    )
    repository_context_max_tokens = int(
        override_values.get(
            "repository_context_max_tokens",
            os.getenv(
                "PROJECT_AGENT_REPOSITORY_CONTEXT_MAX_TOKENS",
                config_values.get("repository_context_max_tokens", "6000"),
            ),
        )
    )
    memory_enabled = _parse_bool(
        override_values.get(
            "memory_enabled",
            os.getenv("PROJECT_AGENT_MEMORY_ENABLED", config_values.get("memory_enabled", "true")),
        )
    )
    memory_dir = _parse_path(
        override_values.get(
            "memory_dir",
            os.getenv(
                "PROJECT_AGENT_MEMORY_DIR",
                config_values.get("memory_dir", str(workspace_root / ".project_agent" / "memory")),
            ),
        ),
        workspace_root=workspace_root,
    )
    memory_entrypoint_max_lines = int(
        override_values.get(
            "memory_entrypoint_max_lines",
            os.getenv(
                "PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_LINES",
                config_values.get("memory_entrypoint_max_lines", "200"),
            ),
        )
    )
    memory_entrypoint_max_bytes = int(
        override_values.get(
            "memory_entrypoint_max_bytes",
            os.getenv(
                "PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_BYTES",
                config_values.get("memory_entrypoint_max_bytes", "25000"),
            ),
        )
    )
    memory_max_relevant_files = int(
        override_values.get(
            "memory_max_relevant_files",
            os.getenv(
                "PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILES",
                config_values.get("memory_max_relevant_files", "3"),
            ),
        )
    )
    memory_max_relevant_file_chars = int(
        override_values.get(
            "memory_max_relevant_file_chars",
            os.getenv(
                "PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILE_CHARS",
                config_values.get("memory_max_relevant_file_chars", "3000"),
            ),
        )
    )
    memory_max_manifest_files = int(
        override_values.get(
            "memory_max_manifest_files",
            os.getenv(
                "PROJECT_AGENT_MEMORY_MAX_MANIFEST_FILES",
                config_values.get("memory_max_manifest_files", "50"),
            ),
        )
    )
    multi_agent_enabled = _parse_bool(
        override_values.get(
            "multi_agent_enabled",
            os.getenv(
                "PROJECT_AGENT_MULTI_AGENT_ENABLED",
                config_values.get("multi_agent_enabled", "true"),
            ),
        )
    )
    coordinator_enabled = _parse_bool(
        override_values.get(
            "coordinator_enabled",
            os.getenv(
                "PROJECT_AGENT_COORDINATOR_ENABLED",
                config_values.get("coordinator_enabled", "false"),
            ),
        )
    )
    max_subagents_per_turn = int(
        override_values.get(
            "max_subagents_per_turn",
            os.getenv(
                "PROJECT_AGENT_MAX_SUBAGENTS_PER_TURN",
                config_values.get("max_subagents_per_turn", "4"),
            ),
        )
    )
    max_subagent_steps = int(
        override_values.get(
            "max_subagent_steps",
            os.getenv(
                "PROJECT_AGENT_MAX_SUBAGENT_STEPS",
                config_values.get("max_subagent_steps", "12"),
            ),
        )
    )
    max_worker_result_chars = int(
        override_values.get(
            "max_worker_result_chars",
            os.getenv(
                "PROJECT_AGENT_MAX_WORKER_RESULT_CHARS",
                config_values.get("max_worker_result_chars", "8000"),
            ),
        )
    )
    allow_recursive_subagents = _parse_bool(
        override_values.get(
            "allow_recursive_subagents",
            os.getenv(
                "PROJECT_AGENT_ALLOW_RECURSIVE_SUBAGENTS",
                config_values.get("allow_recursive_subagents", "false"),
            ),
        )
    )

    _validate_log_level(log_level)
    _validate_max_steps(max_steps)
    _validate_positive_number(command_timeout_seconds, "command_timeout_seconds")
    _validate_positive_int(max_command_output_chars, "max_command_output_chars")
    _validate_positive_int(max_file_read_chars, "max_file_read_chars")
    _validate_positive_int(max_repository_context_chars, "max_repository_context_chars")
    _validate_positive_int(max_git_diff_chars, "max_git_diff_chars")
    _validate_positive_int(max_rule_file_chars, "max_rule_file_chars")
    _validate_positive_int(max_relevant_files, "max_relevant_files")
    _validate_positive_int(max_relevant_file_chars, "max_relevant_file_chars")
    _validate_positive_int(recent_commits_count, "recent_commits_count")
    _validate_positive_number(context_command_timeout_seconds, "context_command_timeout_seconds")
    _validate_positive_int(skills_max_composition_depth, "skills_max_composition_depth")
    _validate_positive_int(skills_max_expansion_chars, "skills_max_expansion_chars")
    _validate_positive_int(context_window_tokens, "context_window_tokens")
    _validate_ratio(context_trigger_fill_ratio, "context_trigger_fill_ratio")
    _validate_ratio(context_recover_fill_ratio, "context_recover_fill_ratio")
    if context_recover_fill_ratio >= context_trigger_fill_ratio:
        raise ConfigurationError("context_recover_fill_ratio must be < context_trigger_fill_ratio")
    _validate_positive_int(context_circuit_breaker_failures, "context_circuit_breaker_failures")
    _validate_positive_int(context_recent_tool_results_keep, "context_recent_tool_results_keep")
    _validate_positive_int(context_tool_result_preview_chars, "context_tool_result_preview_chars")
    _validate_positive_int(context_summary_max_tokens, "context_summary_max_tokens")
    _validate_positive_int(repository_context_max_tokens, "repository_context_max_tokens")
    _validate_positive_int(memory_entrypoint_max_lines, "memory_entrypoint_max_lines")
    _validate_positive_int(memory_entrypoint_max_bytes, "memory_entrypoint_max_bytes")
    _validate_positive_int(memory_max_relevant_files, "memory_max_relevant_files")
    _validate_positive_int(memory_max_relevant_file_chars, "memory_max_relevant_file_chars")
    _validate_positive_int(memory_max_manifest_files, "memory_max_manifest_files")
    _validate_positive_int(max_subagents_per_turn, "max_subagents_per_turn")
    if max_subagents_per_turn > 16:
        raise ConfigurationError("max_subagents_per_turn must be <= 16")
    _validate_positive_int(max_subagent_steps, "max_subagent_steps")
    _validate_positive_int(max_worker_result_chars, "max_worker_result_chars")
    _validate_path_within_workspace(memory_dir, workspace_root, "memory_dir")
    _validate_non_empty_string(context_profile, "context_profile")
    _validate_non_empty_string(context_profile_version, "context_profile_version")

    return Settings(
        workspace_root=workspace_root,
        log_level=log_level,
        default_model=default_model,
        model_base_url=model_base_url or None,
        model_api_key=model_api_key or None,
        environment=environment,
        session_store_dir=session_store_dir,
        max_steps=max_steps,
        stream_output=stream_output,
        command_timeout_seconds=command_timeout_seconds,
        max_command_output_chars=max_command_output_chars,
        max_file_read_chars=max_file_read_chars,
        enable_repository_context=enable_repository_context,
        max_repository_context_chars=max_repository_context_chars,
        max_git_diff_chars=max_git_diff_chars,
        max_rule_file_chars=max_rule_file_chars,
        max_relevant_files=max_relevant_files,
        max_relevant_file_chars=max_relevant_file_chars,
        recent_commits_count=recent_commits_count,
        context_command_timeout_seconds=context_command_timeout_seconds,
        skills_enabled=skills_enabled,
        skills_builtin_enabled=skills_builtin_enabled,
        project_skills_dir=project_skills_dir,
        user_skills_dir=user_skills_dir,
        skills_allow_command_substitution=skills_allow_command_substitution,
        skills_max_composition_depth=skills_max_composition_depth,
        skills_max_expansion_chars=skills_max_expansion_chars,
        permission_mode=permission_mode,
        permission_rules_file=permission_rules_file,
        context_window_tokens=context_window_tokens,
        context_trigger_fill_ratio=context_trigger_fill_ratio,
        context_recover_fill_ratio=context_recover_fill_ratio,
        context_circuit_breaker_failures=context_circuit_breaker_failures,
        context_recent_tool_results_keep=context_recent_tool_results_keep,
        context_tool_result_preview_chars=context_tool_result_preview_chars,
        context_summary_max_tokens=context_summary_max_tokens,
        context_profile=context_profile,
        context_profile_version=context_profile_version,
        enable_auto_compaction=enable_auto_compaction,
        enable_full_compaction=enable_full_compaction,
        repository_context_max_tokens=repository_context_max_tokens,
        memory_enabled=memory_enabled,
        memory_dir=memory_dir,
        memory_entrypoint_max_lines=memory_entrypoint_max_lines,
        memory_entrypoint_max_bytes=memory_entrypoint_max_bytes,
        memory_max_relevant_files=memory_max_relevant_files,
        memory_max_relevant_file_chars=memory_max_relevant_file_chars,
        memory_max_manifest_files=memory_max_manifest_files,
        multi_agent_enabled=multi_agent_enabled,
        coordinator_enabled=coordinator_enabled,
        max_subagents_per_turn=max_subagents_per_turn,
        max_subagent_steps=max_subagent_steps,
        max_worker_result_chars=max_worker_result_chars,
        allow_recursive_subagents=allow_recursive_subagents,
    )


def _load_config_file(config_path: Path) -> dict[str, str]:
    try:
        raw_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(f"failed to read config file: {config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"failed to parse config file: {config_path}") from error

    project_config = raw_config.get("project_agent", {})
    if not isinstance(project_config, dict):
        raise ConfigurationError("invalid [project_agent] section")

    values: dict[str, str] = {}
    for key, value in project_config.items():
        if not isinstance(value, (str, int, float, bool)):
            raise ConfigurationError(f"invalid config value for {key}")
        values[key] = str(value)

    return values


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"invalid boolean value: {value}")


def _parse_optional_path(value: str, *, workspace_root: Path) -> Path | None:
    normalized = value.strip()
    if not normalized:
        return None
    return _parse_path(normalized, workspace_root=workspace_root)


def _parse_path(value: str, *, workspace_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = workspace_root / path
    return path.resolve()


def _parse_permission_mode(value: str) -> PermissionMode:
    try:
        return PermissionMode(value.strip().lower())
    except ValueError as error:
        raise ConfigurationError(f"invalid permission mode: {value}") from error


def _validate_log_level(log_level: str) -> None:
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigurationError(f"invalid log level: {log_level}")


def _validate_max_steps(max_steps: int) -> None:
    if max_steps < 1:
        raise ConfigurationError("max_steps must be >= 1")


def _validate_positive_number(value: float, key: str) -> None:
    if value <= 0:
        raise ConfigurationError(f"{key} must be > 0")


def _validate_positive_int(value: int, key: str) -> None:
    if value < 1:
        raise ConfigurationError(f"{key} must be >= 1")


def _validate_ratio(value: float, key: str) -> None:
    if value <= 0 or value >= 1:
        raise ConfigurationError(f"{key} must be > 0 and < 1")


def _validate_non_empty_string(value: str, key: str) -> None:
    if not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")


def _validate_path_within_workspace(path: Path, workspace_root: Path, key: str) -> None:
    try:
        path.relative_to(workspace_root)
    except ValueError as error:
        raise ConfigurationError(f"{key} must be within workspace_root") from error
