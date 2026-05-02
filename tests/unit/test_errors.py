from project_agent.errors import AgentError, ConfigurationError, map_exception_to_exit_code


def test_agent_error_uses_its_exit_code() -> None:
    error = AgentError("boom", exit_code=3)

    assert map_exception_to_exit_code(error) == 3


def test_configuration_error_uses_stable_exit_code() -> None:
    error = ConfigurationError("invalid config")

    assert error.exit_code == 2
    assert map_exception_to_exit_code(error) == 2


def test_unknown_error_uses_default_exit_code() -> None:
    assert map_exception_to_exit_code(RuntimeError("boom")) == 1
