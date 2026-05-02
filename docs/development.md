# Development

## Local commands

```bash
pip install -e .[dev]
pytest
ruff check .
ruff format --check .
mypy src
```

## Startup verification

```bash
project-agent --help
project-agent version
project-agent doctor
```

## Configuration notes

- Use `examples/basic_config.toml` as the baseline config file format.
- The loader reads the `[project_agent]` section only.
- Invalid TOML or unsupported `log_level` values fail fast with exit code `2`.
