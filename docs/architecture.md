# Architecture

Phase 0 establishes the Python package layout, a Typer-based CLI entrypoint, configuration loading, logging, error handling, and core protocol abstractions for future agent runtime work.

## Startup baseline

- Installed console script: `project-agent`
- Console script entrypoint: `project_agent.cli:main_entry`
- CLI callback loads settings, configures logging, and stores settings in Typer context
- Startup failures are mapped through the `AgentError` hierarchy

## Configuration baseline

The configuration loader reads TOML under the `[project_agent]` section and resolves values in this order:

1. CLI options
2. Environment variables
3. Config file
4. Defaults

Phase 0 validates `log_level` during startup and raises a configuration error for malformed config files or invalid values.
