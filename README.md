# project-agent

Open-source Python CLI agent framework inspired by Claude Code.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
project-agent --help
pytest
ruff check .
ruff format --check .
mypy src
```

## Commands

- `project-agent --help`
- `project-agent doctor`
- `project-agent version`
- `project-agent run`

## Configuration precedence

Settings are resolved in this order:

1. CLI options
2. Environment variables
3. TOML config file in `[project_agent]`
4. Built-in defaults

Supported environment variables:

- `PROJECT_AGENT_WORKSPACE_ROOT`
- `PROJECT_AGENT_LOG_LEVEL`
- `PROJECT_AGENT_DEFAULT_MODEL`
- `PROJECT_AGENT_MODEL_BASE_URL`
- `PROJECT_AGENT_API_KEY`
- `PROJECT_AGENT_ENVIRONMENT`

For real model calls, configure any OpenAI-compatible chat completions endpoint:

```bash
export PROJECT_AGENT_MODEL_BASE_URL="https://api.example.com/v1"
export PROJECT_AGENT_API_KEY="your-api-key"
export PROJECT_AGENT_DEFAULT_MODEL="your-model"
project-agent run --prompt "summarize this repository"
```

If `PROJECT_AGENT_MODEL_BASE_URL` and `PROJECT_AGENT_API_KEY` are unset, the CLI uses the built-in mock model.

Invalid config content or unsupported `log_level` values fail fast with a configuration error.

## Project layout

- `src/project_agent`: application package
- `tests`: unit tests
- `examples`: example config and plugin skeleton
- `docs`: architecture and development notes
