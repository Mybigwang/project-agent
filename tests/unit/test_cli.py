import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import project_agent.cli as cli_module
from project_agent.cli import app
from project_agent.config import Settings
from project_agent.core.types import AgentTraceStep, Message, SkillCall, Task, TaskPlan
from project_agent.errors import AgentError, ConfigurationError

runner = CliRunner()


@pytest.fixture(autouse=True)
def clear_model_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROJECT_AGENT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("PROJECT_AGENT_API_KEY", raising=False)


def _make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {
        "workspace_root": tmp_path,
        "log_level": "info",
        "default_model": "mock-model",
        "model_base_url": None,
        "model_api_key": None,
        "environment": "development",
        "session_store_dir": tmp_path / ".project_agent" / "sessions",
        "max_steps": 8,
        "stream_output": False,
        "command_timeout_seconds": 30.0,
        "max_command_output_chars": 4000,
        "max_file_read_chars": 12000,
        "enable_repository_context": True,
        "max_repository_context_chars": 20000,
        "max_git_diff_chars": 6000,
        "max_rule_file_chars": 6000,
        "max_relevant_files": 5,
        "max_relevant_file_chars": 3000,
        "recent_commits_count": 5,
        "context_command_timeout_seconds": 5.0,
        "skills_enabled": True,
        "skills_builtin_enabled": True,
        "project_skills_dir": tmp_path / ".project_agent" / "skills",
        "user_skills_dir": None,
        "skills_allow_command_substitution": False,
        "skills_max_composition_depth": 3,
        "skills_max_expansion_chars": 20000,
        **overrides,
    }
    return Settings(**values)


def test_console_script_points_to_main_entry() -> None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["project-agent"] == "project_agent.cli:main_entry"


def test_help_command_succeeds() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Project Agent CLI" in result.stdout


def test_doctor_command_uses_cli_overrides(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--workspace-root", str(tmp_path), "doctor"])

    assert result.exit_code == 0
    assert f"workspace_root={tmp_path.resolve()}" in result.stdout
    assert "model_api_key_configured=False" in result.stdout


def test_run_command_executes_runtime(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello"],
    )

    assert result.exit_code == 0
    assert result.stdout == "Mock response (turn 1): hello\n"


def test_run_command_prints_trace_output(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "use tool ping", "--trace"],
    )

    assert result.exit_code == 0
    assert "Tool result (turn 1): echo: ping" in result.stdout
    assert "[step 1] tool echo ok: echo: ping" in result.stdout


def test_run_command_streams_output_when_enabled(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello", "--stream"],
    )

    assert result.exit_code == 0
    assert "Mock response (turn 1): hello" in result.stdout
    assert "Mock" in result.stdout
    assert "hello" in result.stdout


def test_run_command_streaming_preserves_whitespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class WhitespaceModelClient:
        name = "whitespace-model"

        def complete(
            self,
            *,
            messages: list[Message],
            tools: list[object],
            stream_callback: object | None = None,
        ) -> Message:
            del messages, tools, stream_callback
            return Message(role="assistant", content="line 1\n\nline  2")

    monkeypatch.setattr(cli_module, "MockModelClient", WhitespaceModelClient)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello", "--stream"],
    )

    assert result.exit_code == 0
    assert result.stdout == "line 1\n\nline  2\n"


def test_run_command_sanitizes_final_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class ControlCharacterModelClient:
        name = "control-character-model"

        def complete(
            self,
            *,
            messages: list[Message],
            tools: list[object],
            stream_callback: object | None = None,
        ) -> Message:
            del messages, tools, stream_callback
            return Message(role="assistant", content="ok\x1b[31m\rnext")

    monkeypatch.setattr(cli_module, "MockModelClient", ControlCharacterModelClient)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello"],
    )

    assert result.exit_code == 0
    assert "\x1b" not in result.stdout
    assert "ok?[31m\\rnext" in result.stdout


def test_run_command_streams_saved_response_without_second_model_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class CountingModelClient:
        name = "counting-model"

        def __init__(self) -> None:
            self.complete_calls = 0

        def complete(
            self,
            *,
            messages: list[Message],
            tools: list[object],
            stream_callback: object | None = None,
        ) -> Message:
            del messages, tools, stream_callback
            self.complete_calls += 1
            return Message(role="assistant", content=f"response {self.complete_calls}")

        def stream_complete(
            self, *, messages: list[Message], tools: list[object]
        ) -> tuple[str, ...]:
            raise AssertionError("stream_complete should not be called")

    model_client = CountingModelClient()
    monkeypatch.setattr(cli_module, "MockModelClient", lambda: model_client)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello", "--stream"],
    )

    assert result.exit_code == 0
    assert result.stdout == "response 1\n"
    assert model_client.complete_calls == 1


def test_run_command_uses_settings_stream_output_when_stream_flag_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli_module, "load_settings", lambda **_: _make_settings(tmp_path, stream_output=True)
    )

    def fake_run_once(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli_module, "_run_once", fake_run_once)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello"],
    )

    assert result.exit_code == 0
    assert captured["stream_output"] is True
    assert captured["max_steps"] == 8


@pytest.mark.parametrize(
    ("flag", "expected_stream_output"),
    [("--stream", True), ("--no-stream", False)],
)
def test_run_command_stream_flag_overrides_settings_stream_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flag: str,
    expected_stream_output: bool,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda **_: _make_settings(tmp_path, stream_output=not expected_stream_output),
    )

    def fake_run_once(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli_module, "_run_once", fake_run_once)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello", flag],
    )

    assert result.exit_code == 0
    assert captured["stream_output"] is expected_stream_output


def test_run_command_passes_max_steps_override_to_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli_module, "load_settings", lambda **_: _make_settings(tmp_path, max_steps=8)
    )

    def fake_run_once(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli_module, "_run_once", fake_run_once)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "hello", "--max-steps", "3"],
    )

    assert result.exit_code == 0
    assert captured["max_steps"] == 3


def test_run_command_uses_session_history(tmp_path: Path) -> None:
    runner.invoke(
        app,
        [
            "--workspace-root",
            str(tmp_path),
            "run",
            "--session-id",
            "demo",
            "--prompt",
            "hello",
        ],
    )

    result = runner.invoke(
        app,
        [
            "--workspace-root",
            str(tmp_path),
            "run",
            "--session-id",
            "demo",
            "--prompt",
            "hello again",
        ],
    )

    assert result.exit_code == 0
    assert "Mock response (turn 2): hello again" in result.stdout


def test_run_command_executes_project_skill_prompt(tmp_path: Path) -> None:
    skill_path = tmp_path / ".project_agent" / "skills" / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        (
            "---\n"
            "name: demo\n"
            "description: demo skill\n"
            "---\n"
            "Expanded {{args[0]}}"
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "/demo hello"],
    )

    assert result.exit_code == 0
    assert result.stdout == "Mock response (turn 1): Skill: demo\n\nExpanded hello\n"


def test_run_command_reports_unknown_skill_command(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "/missing"],
    )

    assert result.exit_code == 0
    assert "Unknown command: /missing" in result.stdout




def test_run_command_streaming_shows_skill_notification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    skill_path = tmp_path / ".project_agent" / "skills" / "review-change" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        (
            "---\n"
            "name: review-change\n"
            "description: review code changes\n"
            "when_to_use: when the user asks for a review\n"
            "---\n"
            "Review target {{args[0]}}"
        ),
        encoding="utf-8",
    )

    class SkillThenMessageModelClient:
        name = "skill-then-message-model"

        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self,
            *,
            messages: list[Message],
            tools: list[object],
            stream_callback: object | None = None,
        ) -> Message | SkillCall:
            del messages, tools, stream_callback
            self.calls += 1
            if self.calls == 1:
                return SkillCall(name="review-change", raw_args="src/module.py")
            return Message(role="assistant", content="done")

    monkeypatch.setattr(cli_module, "MockModelClient", SkillThenMessageModelClient)

    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run", "--prompt", "please review", "--stream"],
    )

    assert result.exit_code == 0
    assert "正在调用 skill: review-change" in result.stdout
    assert result.stdout.endswith("done\n")


def test_run_command_supports_interactive_mode(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["--workspace-root", str(tmp_path), "run"],
        input="hello\n/exit\n",
    )

    assert result.exit_code == 0
    assert "Mock response (turn 1): hello" in result.stdout
    assert "Exiting interactive mode." in result.stdout


def test_run_command_passes_repository_context_settings_to_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    settings = _make_settings(
        tmp_path,
        enable_repository_context=False,
        max_repository_context_chars=111,
        max_git_diff_chars=112,
        max_rule_file_chars=113,
        max_relevant_files=2,
        max_relevant_file_chars=114,
        recent_commits_count=3,
        context_command_timeout_seconds=4.0,
    )
    monkeypatch.setattr(cli_module, "load_settings", lambda **_: settings)

    def fake_run_once(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli_module, "_run_once", fake_run_once)

    result = runner.invoke(app, ["--workspace-root", str(tmp_path), "run", "--prompt", "hello"])

    assert result.exit_code == 0
    assert captured["enable_repository_context"] is False
    builder = captured["repository_context_builder"]
    assert builder is not None
    assert builder.max_repository_context_chars == 111
    assert builder.max_git_diff_chars == 112
    assert builder.max_rule_file_chars == 113
    assert builder.max_relevant_files == 2
    assert builder.max_relevant_file_chars == 114
    assert builder.recent_commits_count == 3
    assert builder.context_command_timeout_seconds == 4.0


def test_task_progress_and_trace_sanitize_control_characters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_plan = TaskPlan(tasks=(Task(id="task_1", title="bad\x1b[31m\r\ntext", description="bad"),))
    trace = (
        AgentTraceStep(
            step=1,
            event="task",
            summary="started\x1b\r\nsummary",
            task_id="task_1",
            task_status="in_progress",
        ),
    )

    cli_module._echo_task_progress(task_plan)
    cli_module._echo_trace(trace)

    captured = capsys.readouterr()
    assert "\x1b" not in captured.out
    assert "bad?[31m\\r\\ntext" in captured.out
    assert "started?\\r\\nsummary" in captured.out


def test_build_model_client_uses_openai_compatible_client_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "project_agent.runtime.model_clients.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 0, "", ("93.184.216.34", 443))],
    )
    settings = _make_settings(
        tmp_path,
        default_model="real-model",
        model_base_url="https://model.example/v1",
        model_api_key="secret-key",
    )

    model_client = cli_module._build_model_client(settings)

    assert model_client.name == "real-model"


def test_main_entry_maps_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def raise_configuration_error() -> None:
        raise ConfigurationError("invalid config")

    monkeypatch.setattr(cli_module, "app", raise_configuration_error)

    exit_code = cli_module.main_entry()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Error: invalid config" in captured.err


def test_main_entry_preserves_agent_error_after_traceback_assignment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def raise_agent_error() -> None:
        error = AgentError("model request failed due to a network error")
        error.__traceback__ = None
        raise error

    monkeypatch.setattr(cli_module, "app", raise_agent_error)

    exit_code = cli_module.main_entry()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error: model request failed due to a network error" in captured.err


def test_main_entry_prints_unexpected_error_type_without_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def raise_runtime_error() -> None:
        raise RuntimeError("secret-token\x1b[31m\r\nnext")

    monkeypatch.setattr(cli_module, "app", raise_runtime_error)

    exit_code = cli_module.main_entry()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error: unexpected failure: RuntimeError" in captured.err
    assert "secret-token" not in captured.err
    assert "\x1b" not in captured.err
