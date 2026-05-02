from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from project_agent.errors import ConfigurationError

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
            os.getenv("PROJECT_AGENT_MAX_STEPS", config_values.get("max_steps", "8")),
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
