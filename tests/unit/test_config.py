from pathlib import Path

import pytest

from project_agent.config import load_settings
from project_agent.errors import ConfigurationError


def test_load_settings_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROJECT_AGENT_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_LOG_LEVEL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_STEPS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_STREAM_OUTPUT", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_COMMAND_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_COMMAND_OUTPUT_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_FILE_READ_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_ENABLE_REPOSITORY_CONTEXT", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_REPOSITORY_CONTEXT_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_GIT_DIFF_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_RULE_FILE_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_RELEVANT_FILES", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MAX_RELEVANT_FILE_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_RECENT_COMMITS_COUNT", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_COMMAND_TIMEOUT_SECONDS", raising=False)

    settings = load_settings()

    assert settings.log_level == "info"
    assert settings.default_model == "mock-model"
    assert settings.model_base_url is None
    assert settings.model_api_key is None
    assert settings.environment == "development"
    assert settings.max_steps == 8
    assert settings.stream_output is False
    assert settings.command_timeout_seconds == 30.0
    assert settings.max_command_output_chars == 4000
    assert settings.max_file_read_chars == 12000
    assert settings.enable_repository_context is True
    assert settings.max_repository_context_chars == 20000
    assert settings.max_git_diff_chars == 6000
    assert settings.max_rule_file_chars == 6000
    assert settings.max_relevant_files == 5
    assert settings.max_relevant_file_chars == 3000
    assert settings.recent_commits_count == 5
    assert settings.context_command_timeout_seconds == 5.0


def test_load_settings_honors_override_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    env_root = tmp_path / "env-root"
    config_path.write_text(
        (
            "[project_agent]\n"
            "workspace_root = '.'\n"
            "log_level = 'warning'\n"
            "default_model = 'config-model'\n"
            "model_base_url = 'https://config.example/v1'\n"
            "model_api_key = 'config-key'\n"
            "environment = 'test'\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_WORKSPACE_ROOT", str(env_root))
    monkeypatch.setenv("PROJECT_AGENT_LOG_LEVEL", "error")
    monkeypatch.setenv("PROJECT_AGENT_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("PROJECT_AGENT_MODEL_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("PROJECT_AGENT_API_KEY", "env-key")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "default_model": "cli-model",
            "model_base_url": "https://cli.example/v1",
            "model_api_key": "cli-key",
            "environment": "cli",
        },
    )

    assert settings.workspace_root == env_root.resolve()
    assert settings.log_level == "error"
    assert settings.default_model == "cli-model"
    assert settings.model_base_url == "https://cli.example/v1"
    assert settings.model_api_key == "cli-key"
    assert settings.environment == "cli"


def test_load_settings_honors_phase2_override_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[project_agent]\n"
            "max_steps = 3\n"
            "stream_output = false\n"
            "command_timeout_seconds = 10\n"
            "max_command_output_chars = 100\n"
            "max_file_read_chars = 200\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_MAX_STEPS", "4")
    monkeypatch.setenv("PROJECT_AGENT_STREAM_OUTPUT", "true")
    monkeypatch.setenv("PROJECT_AGENT_COMMAND_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("PROJECT_AGENT_MAX_COMMAND_OUTPUT_CHARS", "300")
    monkeypatch.setenv("PROJECT_AGENT_MAX_FILE_READ_CHARS", "400")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "max_steps": "5",
            "stream_output": "false",
            "command_timeout_seconds": "6",
            "max_command_output_chars": "700",
            "max_file_read_chars": "800",
        },
    )

    assert settings.max_steps == 5
    assert settings.stream_output is False
    assert settings.command_timeout_seconds == 6.0
    assert settings.max_command_output_chars == 700
    assert settings.max_file_read_chars == 800


def test_load_settings_raises_on_malformed_config(tmp_path: Path) -> None:
    config_path = tmp_path / "broken.toml"
    config_path.write_text("[project_agent]\nlog_level = [\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="failed to parse config file"):
        load_settings(config_path=config_path)


def test_load_settings_raises_on_invalid_log_level(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\nlog_level = 'verbose'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="invalid log level"):
        load_settings(config_path=config_path)


def test_load_settings_raises_on_invalid_stream_output(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\nstream_output = 'maybe'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="invalid boolean value"):
        load_settings(config_path=config_path)


@pytest.mark.parametrize(
    ("config_line", "error_message"),
    [
        ("command_timeout_seconds = 0\n", "command_timeout_seconds must be > 0"),
        ("max_command_output_chars = 0\n", "max_command_output_chars must be >= 1"),
        ("max_file_read_chars = 0\n", "max_file_read_chars must be >= 1"),
    ],
)
def test_load_settings_raises_on_non_positive_phase2_limits(
    tmp_path: Path,
    config_line: str,
    error_message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[project_agent]\n{config_line}",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match=error_message):
        load_settings(config_path=config_path)


def test_load_settings_honors_phase3_override_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[project_agent]\n"
            "enable_repository_context = false\n"
            "max_repository_context_chars = 100\n"
            "max_git_diff_chars = 101\n"
            "max_rule_file_chars = 102\n"
            "max_relevant_files = 2\n"
            "max_relevant_file_chars = 103\n"
            "recent_commits_count = 3\n"
            "context_command_timeout_seconds = 4\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_ENABLE_REPOSITORY_CONTEXT", "true")
    monkeypatch.setenv("PROJECT_AGENT_MAX_REPOSITORY_CONTEXT_CHARS", "200")
    monkeypatch.setenv("PROJECT_AGENT_MAX_GIT_DIFF_CHARS", "201")
    monkeypatch.setenv("PROJECT_AGENT_MAX_RULE_FILE_CHARS", "202")
    monkeypatch.setenv("PROJECT_AGENT_MAX_RELEVANT_FILES", "4")
    monkeypatch.setenv("PROJECT_AGENT_MAX_RELEVANT_FILE_CHARS", "203")
    monkeypatch.setenv("PROJECT_AGENT_RECENT_COMMITS_COUNT", "5")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_COMMAND_TIMEOUT_SECONDS", "6")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "enable_repository_context": "false",
            "max_repository_context_chars": "300",
            "max_git_diff_chars": "301",
            "max_rule_file_chars": "302",
            "max_relevant_files": "6",
            "max_relevant_file_chars": "303",
            "recent_commits_count": "7",
            "context_command_timeout_seconds": "8",
        },
    )

    assert settings.enable_repository_context is False
    assert settings.max_repository_context_chars == 300
    assert settings.max_git_diff_chars == 301
    assert settings.max_rule_file_chars == 302
    assert settings.max_relevant_files == 6
    assert settings.max_relevant_file_chars == 303
    assert settings.recent_commits_count == 7
    assert settings.context_command_timeout_seconds == 8.0


@pytest.mark.parametrize(
    ("config_line", "error_message"),
    [
        ("max_repository_context_chars = 0\n", "max_repository_context_chars must be >= 1"),
        ("max_git_diff_chars = 0\n", "max_git_diff_chars must be >= 1"),
        ("max_rule_file_chars = 0\n", "max_rule_file_chars must be >= 1"),
        ("max_relevant_files = 0\n", "max_relevant_files must be >= 1"),
        ("max_relevant_file_chars = 0\n", "max_relevant_file_chars must be >= 1"),
        ("recent_commits_count = 0\n", "recent_commits_count must be >= 1"),
        ("context_command_timeout_seconds = 0\n", "context_command_timeout_seconds must be > 0"),
    ],
)
def test_load_settings_raises_on_non_positive_phase3_limits(
    tmp_path: Path,
    config_line: str,
    error_message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[project_agent]\n{config_line}",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=error_message):
        load_settings(config_path=config_path)
