from pathlib import Path

import pytest

from project_agent.config import load_settings
from project_agent.runtime.permissions import PermissionMode
from project_agent.errors import ConfigurationError


def test_load_settings_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROJECT_AGENT_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_LOG_LEVEL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_PROMPT_CACHE", raising=False)
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
    monkeypatch.delenv("PROJECT_AGENT_SKILLS_ENABLED", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_SKILLS_BUILTIN_ENABLED", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_PROJECT_SKILLS_DIR", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_USER_SKILLS_DIR", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_SKILLS_ALLOW_COMMAND_SUBSTITUTION", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_SKILLS_MAX_COMPOSITION_DEPTH", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_SKILLS_MAX_EXPANSION_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_WINDOW_TOKENS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_TRIGGER_FILL_RATIO", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_RECOVER_FILL_RATIO", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_CIRCUIT_BREAKER_FAILURES", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_RECENT_TOOL_RESULTS_KEEP", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_TOOL_RESULT_PREVIEW_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_SUMMARY_MAX_TOKENS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_PROFILE", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_CONTEXT_PROFILE_VERSION", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_ENABLE_AUTO_COMPACTION", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_ENABLE_FULL_COMPACTION", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_REPOSITORY_CONTEXT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_DIR", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_LINES", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_BYTES", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILES", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILE_CHARS", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_MEMORY_MAX_MANIFEST_FILES", raising=False)

    settings = load_settings()

    assert settings.log_level == "info"
    assert settings.default_model == "mock-model"
    assert settings.model_base_url is None
    assert settings.model_api_key is None
    assert settings.prompt_cache == "auto"
    assert settings.environment == "development"
    assert settings.max_steps == 24
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
    assert settings.skills_enabled is True
    assert settings.skills_builtin_enabled is True
    assert settings.project_skills_dir == (settings.workspace_root / ".project_agent" / "skills").resolve()
    assert settings.user_skills_dir is None
    assert settings.skills_allow_command_substitution is False
    assert settings.skills_max_composition_depth == 3
    assert settings.skills_max_expansion_chars == 20000
    assert settings.permission_mode == PermissionMode.DEFAULT
    assert settings.permission_rules_file is None
    assert settings.context_window_tokens == 200000
    assert settings.context_trigger_fill_ratio == 0.87
    assert settings.context_recover_fill_ratio == 0.82
    assert settings.context_circuit_breaker_failures == 3
    assert settings.context_recent_tool_results_keep == 5
    assert settings.context_tool_result_preview_chars == 400
    assert settings.context_summary_max_tokens == 4000
    assert settings.context_profile == "compact-default"
    assert settings.context_profile_version == "2026-05-12"
    assert settings.enable_auto_compaction is True
    assert settings.enable_full_compaction is True
    assert settings.repository_context_max_tokens == 6000
    assert settings.memory_enabled is True
    assert settings.memory_dir == (settings.workspace_root / ".project_agent" / "memory").resolve()
    assert settings.memory_entrypoint_max_lines == 200
    assert settings.memory_entrypoint_max_bytes == 25000
    assert settings.memory_max_relevant_files == 3
    assert settings.memory_max_relevant_file_chars == 3000
    assert settings.memory_max_manifest_files == 50
    assert settings.multi_agent_enabled is True
    assert settings.coordinator_enabled is False
    assert settings.max_subagents_per_turn == 4
    assert settings.max_subagent_steps == 12
    assert settings.max_worker_result_chars == 8000
    assert settings.multi_agent_strict_task_specs is True


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
            "prompt_cache = 'off'\n"
            "environment = 'test'\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_WORKSPACE_ROOT", str(env_root))
    monkeypatch.setenv("PROJECT_AGENT_LOG_LEVEL", "error")
    monkeypatch.setenv("PROJECT_AGENT_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("PROJECT_AGENT_MODEL_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("PROJECT_AGENT_API_KEY", "env-key")
    monkeypatch.setenv("PROJECT_AGENT_PROMPT_CACHE", "on")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "default_model": "cli-model",
            "model_base_url": "https://cli.example/v1",
            "model_api_key": "cli-key",
            "prompt_cache": "off",
            "environment": "cli",
        },
    )

    assert settings.workspace_root == env_root.resolve()
    assert settings.log_level == "error"
    assert settings.default_model == "cli-model"
    assert settings.model_base_url == "https://cli.example/v1"
    assert settings.model_api_key == "cli-key"
    assert settings.prompt_cache == "off"
    assert settings.environment == "cli"


@pytest.mark.parametrize("value", ["auto", "on", "off"])
def test_load_settings_accepts_prompt_cache_modes(
    tmp_path: Path,
    value: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[project_agent]\nprompt_cache = '{value}'\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path)

    assert settings.prompt_cache == value


def test_load_settings_rejects_invalid_prompt_cache_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\nprompt_cache = 'maybe'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="invalid prompt_cache"):
        load_settings(config_path=config_path)


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


def test_load_settings_honors_multi_agent_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[project_agent]\n"
            "multi_agent_enabled = false\n"
            "coordinator_enabled = true\n"
            "max_subagents_per_turn = 2\n"
            "max_subagent_steps = 5\n"
            "max_worker_result_chars = 1000\n"
            "multi_agent_strict_task_specs = false\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_MAX_SUBAGENTS_PER_TURN", "3")

    settings = load_settings(
        config_path=config_path,
        overrides={"max_subagents_per_turn": "6"},
    )

    assert settings.multi_agent_enabled is False
    assert settings.coordinator_enabled is True
    assert settings.max_subagents_per_turn == 6
    assert settings.max_subagent_steps == 5
    assert settings.max_worker_result_chars == 1000
    assert settings.multi_agent_strict_task_specs is False


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
        ("max_subagents_per_turn = 0\n", "max_subagents_per_turn must be >= 1"),
        ("max_subagent_steps = 0\n", "max_subagent_steps must be >= 1"),
        ("max_worker_result_chars = 0\n", "max_worker_result_chars must be >= 1"),
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
        ("skills_max_composition_depth = 0\n", "skills_max_composition_depth must be >= 1"),
        ("skills_max_expansion_chars = 0\n", "skills_max_expansion_chars must be >= 1"),
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


def test_load_settings_supports_skill_specific_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[project_agent]\n"
            "skills_enabled = false\n"
            "skills_builtin_enabled = false\n"
            "project_skills_dir = 'from-config-project'\n"
            "user_skills_dir = 'from-config-user'\n"
            "skills_allow_command_substitution = true\n"
            "skills_max_composition_depth = 9\n"
            "skills_max_expansion_chars = 999\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_SKILLS_ENABLED", "true")
    monkeypatch.setenv("PROJECT_AGENT_SKILLS_BUILTIN_ENABLED", "true")
    monkeypatch.setenv("PROJECT_AGENT_PROJECT_SKILLS_DIR", str(tmp_path / "from-env-project"))
    monkeypatch.setenv("PROJECT_AGENT_USER_SKILLS_DIR", str(tmp_path / "from-env-user"))
    monkeypatch.setenv("PROJECT_AGENT_SKILLS_ALLOW_COMMAND_SUBSTITUTION", "false")
    monkeypatch.setenv("PROJECT_AGENT_SKILLS_MAX_COMPOSITION_DEPTH", "10")
    monkeypatch.setenv("PROJECT_AGENT_SKILLS_MAX_EXPANSION_CHARS", "1000")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "skills_enabled": "false",
            "skills_builtin_enabled": "false",
            "project_skills_dir": str(tmp_path / "from-cli-project"),
            "user_skills_dir": str(tmp_path / "from-cli-user"),
            "skills_allow_command_substitution": "true",
            "skills_max_composition_depth": "11",
            "skills_max_expansion_chars": "1111",
        },
    )

    assert settings.skills_enabled is False
    assert settings.skills_builtin_enabled is False
    assert settings.project_skills_dir == (tmp_path / "from-cli-project").resolve()
    assert settings.user_skills_dir == (tmp_path / "from-cli-user").resolve()
    assert settings.skills_allow_command_substitution is True
    assert settings.skills_max_composition_depth == 11
    assert settings.skills_max_expansion_chars == 1111


def test_load_settings_supports_permission_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\npermission_mode = 'accept_edits'\npermission_rules_file = 'rules.toml'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_PERMISSION_MODE", "dont_ask")
    monkeypatch.setenv("PROJECT_AGENT_PERMISSION_RULES_FILE", str(tmp_path / "env-rules.toml"))

    settings = load_settings(
        config_path=config_path,
        overrides={
            "permission_mode": "plan",
            "permission_rules_file": str(tmp_path / "cli-rules.toml"),
        },
    )

    assert settings.permission_mode == PermissionMode.PLAN
    assert settings.permission_rules_file == (tmp_path / "cli-rules.toml").resolve()


def test_load_settings_rejects_invalid_permission_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\npermission_mode = 'invalid'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="invalid permission mode"):
        load_settings(config_path=config_path)


def test_load_settings_rejects_removed_auto_permission_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\npermission_mode = 'auto'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="invalid permission mode"):
        load_settings(config_path=config_path)


def test_load_settings_supports_context_management_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[project_agent]\n"
            "context_window_tokens = 1000\n"
            "context_trigger_fill_ratio = 0.8\n"
            "context_recover_fill_ratio = 0.7\n"
            "context_circuit_breaker_failures = 2\n"
            "context_recent_tool_results_keep = 4\n"
            "context_tool_result_preview_chars = 120\n"
            "context_summary_max_tokens = 600\n"
            "context_profile = 'config-profile'\n"
            "context_profile_version = 'v1'\n"
            "enable_auto_compaction = false\n"
            "enable_full_compaction = false\n"
            "repository_context_max_tokens = 300\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_WINDOW_TOKENS", "2000")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_TRIGGER_FILL_RATIO", "0.85")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_RECOVER_FILL_RATIO", "0.75")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_CIRCUIT_BREAKER_FAILURES", "3")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_RECENT_TOOL_RESULTS_KEEP", "5")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_TOOL_RESULT_PREVIEW_CHARS", "240")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_SUMMARY_MAX_TOKENS", "700")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_PROFILE", "env-profile")
    monkeypatch.setenv("PROJECT_AGENT_CONTEXT_PROFILE_VERSION", "env-v1")
    monkeypatch.setenv("PROJECT_AGENT_ENABLE_AUTO_COMPACTION", "true")
    monkeypatch.setenv("PROJECT_AGENT_ENABLE_FULL_COMPACTION", "true")
    monkeypatch.setenv("PROJECT_AGENT_REPOSITORY_CONTEXT_MAX_TOKENS", "500")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "context_window_tokens": "3000",
            "context_trigger_fill_ratio": "0.86",
            "context_recover_fill_ratio": "0.76",
            "context_circuit_breaker_failures": "4",
            "context_recent_tool_results_keep": "6",
            "context_tool_result_preview_chars": "360",
            "context_summary_max_tokens": "800",
            "context_profile": "cli-profile",
            "context_profile_version": "cli-v1",
            "enable_auto_compaction": "false",
            "enable_full_compaction": "false",
            "repository_context_max_tokens": "700",
        },
    )

    assert settings.context_window_tokens == 3000
    assert settings.context_trigger_fill_ratio == 0.86
    assert settings.context_recover_fill_ratio == 0.76
    assert settings.context_circuit_breaker_failures == 4
    assert settings.context_recent_tool_results_keep == 6
    assert settings.context_tool_result_preview_chars == 360
    assert settings.context_summary_max_tokens == 800
    assert settings.context_profile == "cli-profile"
    assert settings.context_profile_version == "cli-v1"
    assert settings.enable_auto_compaction is False
    assert settings.enable_full_compaction is False
    assert settings.repository_context_max_tokens == 700


@pytest.mark.parametrize(
    ("config_line", "error_message"),
    [
        ("context_window_tokens = 0\n", "context_window_tokens must be >= 1"),
        (
            "context_trigger_fill_ratio = 1\n",
            "context_trigger_fill_ratio must be > 0 and < 1",
        ),
        (
            "context_recover_fill_ratio = 0\n",
            "context_recover_fill_ratio must be > 0 and < 1",
        ),
        (
            "context_circuit_breaker_failures = 0\n",
            "context_circuit_breaker_failures must be >= 1",
        ),
        (
            "context_recent_tool_results_keep = 0\n",
            "context_recent_tool_results_keep must be >= 1",
        ),
        (
            "context_tool_result_preview_chars = 0\n",
            "context_tool_result_preview_chars must be >= 1",
        ),
        (
            "context_summary_max_tokens = 0\n",
            "context_summary_max_tokens must be >= 1",
        ),
        (
            "repository_context_max_tokens = 0\n",
            "repository_context_max_tokens must be >= 1",
        ),
    ],
)
def test_load_settings_rejects_invalid_context_management_limits(
    tmp_path: Path,
    config_line: str,
    error_message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[project_agent]\n{config_line}", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=error_message):
        load_settings(config_path=config_path)


def test_load_settings_rejects_context_recover_ratio_not_below_trigger(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[project_agent]\ncontext_trigger_fill_ratio = 0.8\ncontext_recover_fill_ratio = 0.8\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigurationError,
        match="context_recover_fill_ratio must be < context_trigger_fill_ratio",
    ):
        load_settings(config_path=config_path)


@pytest.mark.parametrize("field_name", ["context_profile", "context_profile_version"])
def test_load_settings_rejects_blank_context_identity_fields(tmp_path: Path, field_name: str) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[project_agent]\n{field_name} = '   '\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=f"{field_name} must be a non-empty string"):
        load_settings(config_path=config_path)


def test_load_settings_honors_memory_override_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    workspace_root = tmp_path / "workspace"
    config_path.write_text(
        (
            "[project_agent]\n"
            "memory_enabled = false\n"
            "memory_dir = '.project_agent/config-memory'\n"
            "memory_entrypoint_max_lines = 10\n"
            "memory_entrypoint_max_bytes = 100\n"
            "memory_max_relevant_files = 1\n"
            "memory_max_relevant_file_chars = 200\n"
            "memory_max_manifest_files = 3\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJECT_AGENT_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_DIR", ".project_agent/env-memory")
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_LINES", "20")
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_ENTRYPOINT_MAX_BYTES", "300")
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILES", "2")
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_MAX_RELEVANT_FILE_CHARS", "400")
    monkeypatch.setenv("PROJECT_AGENT_MEMORY_MAX_MANIFEST_FILES", "5")

    settings = load_settings(
        config_path=config_path,
        overrides={
            "memory_enabled": "false",
            "memory_dir": ".project_agent/cli-memory",
            "memory_entrypoint_max_lines": "30",
            "memory_entrypoint_max_bytes": "500",
            "memory_max_relevant_files": "4",
            "memory_max_relevant_file_chars": "600",
            "memory_max_manifest_files": "7",
        },
    )

    assert settings.memory_enabled is False
    assert settings.memory_dir == (workspace_root / ".project_agent" / "cli-memory").resolve()
    assert settings.memory_entrypoint_max_lines == 30
    assert settings.memory_entrypoint_max_bytes == 500
    assert settings.memory_max_relevant_files == 4
    assert settings.memory_max_relevant_file_chars == 600
    assert settings.memory_max_manifest_files == 7


@pytest.mark.parametrize(
    ("config_line", "error_message"),
    [
        ("memory_entrypoint_max_lines = 0\n", "memory_entrypoint_max_lines must be >= 1"),
        ("memory_entrypoint_max_bytes = 0\n", "memory_entrypoint_max_bytes must be >= 1"),
        ("memory_max_relevant_files = 0\n", "memory_max_relevant_files must be >= 1"),
        ("memory_max_relevant_file_chars = 0\n", "memory_max_relevant_file_chars must be >= 1"),
        ("memory_max_manifest_files = 0\n", "memory_max_manifest_files must be >= 1"),
    ],
)
def test_load_settings_rejects_non_positive_memory_limits(
    tmp_path: Path,
    config_line: str,
    error_message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(f"[project_agent]\n{config_line}", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=error_message):
        load_settings(config_path=config_path)


def test_load_settings_rejects_memory_dir_outside_workspace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    outside = tmp_path / "outside"
    config_path.write_text(
        f"[project_agent]\nworkspace_root = 'workspace'\nmemory_dir = '{outside}'\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="memory_dir must be within workspace_root"):
        load_settings(config_path=config_path)
