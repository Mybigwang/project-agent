from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Literal, Protocol, cast

from project_agent.core.interfaces import Tool
from project_agent.core.types import ToolResult
from project_agent.errors import ConfigurationError
from project_agent.runtime.permissions.types import ToolPermissionCategory

McpTransportType = Literal["stdio", "sse", "ws", "http", "streamable-http"]
MAX_MCP_DESCRIPTION_LENGTH = 2048
MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    type: McpTransportType = "stdio"
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    disabled: bool = False


@dataclass(frozen=True)
class McpConfig:
    servers: dict[str, McpServerConfig]


class McpClientProtocol(Protocol):
    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> dict[str, object]: ...


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str
    remote_name: str
    client: McpClientProtocol
    is_read_only: bool = True
    permission_category: ToolPermissionCategory = ToolPermissionCategory.READ

    def run(self, *, workspace_root: Path, arguments: dict[str, object]) -> ToolResult:
        del workspace_root
        response = self.client.call_tool(tool_name=self.remote_name, arguments=arguments)
        is_error = bool(response.get("isError", False))
        return ToolResult(
            name=self.name,
            content=_format_mcp_content(response.get("content")),
            is_error=is_error,
            error_code="mcp_tool_error" if is_error else None,
            data={"server": self.server_name, "tool": self.remote_name},
        )


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp__{server_name}__{tool_name}"


def build_github_mcp_config() -> dict[str, object]:
    return {
        "mcpServers": {
            "github": {
                "type": "stdio",
                "command": "npx.cmd",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
            }
        }
    }


def load_mcp_config(
    *,
    config_path: Path,
    environment: Mapping[str, str] | None = None,
) -> McpConfig:
    env = environment if environment is not None else os.environ
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigurationError(f"failed to read MCP config file: {config_path}") from error
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"failed to parse MCP config file: {config_path}") from error

    if not isinstance(raw, dict):
        raise ConfigurationError("MCP config must be a JSON object")
    raw_servers = raw.get("mcpServers", {})
    if not isinstance(raw_servers, dict):
        raise ConfigurationError("MCP config mcpServers must be an object")

    servers: dict[str, McpServerConfig] = {}
    for name, raw_server in raw_servers.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError("MCP server names must be non-empty strings")
        if not isinstance(raw_server, dict):
            raise ConfigurationError(f"MCP server {name} must be an object")
        servers[name] = _parse_mcp_server(
            name=name,
            raw_server=raw_server,
            environment=env,
        )
    return McpConfig(servers=servers)


def build_mcp_tools(
    *,
    config_path: Path,
    request_timeout_seconds: float,
    max_description_chars: int = MAX_MCP_DESCRIPTION_LENGTH,
    environment: Mapping[str, str] | None = None,
) -> list[Tool]:
    config = load_mcp_config(config_path=config_path, environment=environment)
    tools: list[Tool] = []
    for server in config.servers.values():
        if server.disabled:
            continue
        if server.type != "stdio":
            continue
        client = McpStdioClient(server, request_timeout_seconds=request_timeout_seconds)
        for tool in client.list_tools(max_description_chars=max_description_chars):
            tools.append(tool)
    return tools


class McpStdioClient:
    def __init__(
        self,
        server: McpServerConfig,
        *,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if server.type != "stdio":
            raise ConfigurationError(
                f"MCP server {server.name} uses unsupported transport: {server.type}"
            )
        if not server.command.strip():
            raise ConfigurationError(f"MCP stdio server {server.name} requires command")
        self._server = server
        self._request_timeout_seconds = request_timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._initialized = False

    def list_tools(
        self,
        *,
        max_description_chars: int = MAX_MCP_DESCRIPTION_LENGTH,
    ) -> list[McpTool]:
        self._ensure_initialized()
        response = self._request(method="tools/list", params={})
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise RuntimeError("MCP tools/list result must be an object")
        raw_tools = result.get("tools", [])
        if not isinstance(raw_tools, list):
            raise RuntimeError("MCP tools/list tools must be a list")

        tools: list[McpTool] = []
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                continue
            remote_name = raw_tool.get("name")
            if not isinstance(remote_name, str) or not remote_name:
                continue
            description = raw_tool.get("description", "")
            if not isinstance(description, str):
                description = ""
            input_schema = raw_tool.get("inputSchema", {"type": "object"})
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object"}
            tools.append(
                McpTool(
                    name=build_mcp_tool_name(self._server.name, remote_name),
                    description=_truncate_description(description, max_description_chars),
                    input_schema=cast(dict[str, Any], input_schema),
                    server_name=self._server.name,
                    remote_name=remote_name,
                    client=self,
                )
            )
        return tools

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self._ensure_process()
        response = self._request(
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )
        result = response.get("result", {})
        if not isinstance(result, dict):
            raise RuntimeError("MCP tools/call result must be an object")
        return cast(dict[str, object], result)

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        self._process = None

    def _ensure_initialized(self) -> None:
        self._ensure_process()
        if self._initialized:
            return
        self._request(
            method="initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "project-agent", "version": "0.1.0"},
            },
        )
        self._initialized = True

    def _ensure_process(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        env = os.environ.copy()
        if self._server.env:
            env.update(self._server.env)
        self._process = subprocess.Popen(
            [self._server.command, *self._server.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def _request(self, *, method: str, params: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self._ensure_process()
            process = self._require_process()
            request_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            stdin = _require_stream(process.stdin, "stdin")
            stdout = _require_stream(process.stdout, "stdout")
            stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            stdin.flush()
            line = self._readline_with_timeout(stdout)
            if not line:
                raise RuntimeError(f"MCP server {self._server.name} closed stdout")
            response = json.loads(line)
            if not isinstance(response, dict):
                raise RuntimeError("MCP response must be an object")
            error = response.get("error")
            if isinstance(error, dict):
                message = error.get("message", "unknown MCP error")
                raise RuntimeError(f"MCP request failed: {message}")
            if response.get("id") != request_id:
                raise RuntimeError("MCP response id mismatch")
            return cast(dict[str, object], response)

    def _readline_with_timeout(self, stdout: IO[str]) -> str:
        result: list[str] = []
        errors: list[BaseException] = []

        def read() -> None:
            try:
                result.append(stdout.readline())
            except BaseException as error:
                errors.append(error)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(self._request_timeout_seconds)
        if reader.is_alive():
            raise TimeoutError(f"MCP server {self._server.name} request timed out")
        if errors:
            raise errors[0]
        return result[0] if result else ""

    def _require_process(self) -> subprocess.Popen[str]:
        if self._process is None:
            raise RuntimeError("MCP process is not running")
        return self._process


def _parse_mcp_server(
    *,
    name: str,
    raw_server: dict[object, object],
    environment: Mapping[str, str],
) -> McpServerConfig:
    raw_type = raw_server.get("type", "stdio")
    if not isinstance(raw_type, str):
        raise ConfigurationError(f"MCP server {name} type must be a string")
    server_type = raw_type.strip().lower()
    if server_type not in {"stdio", "sse", "ws", "http", "streamable-http"}:
        raise ConfigurationError(f"MCP server {name} has unsupported type: {raw_type}")
    command = raw_server.get("command", "")
    if not isinstance(command, str):
        raise ConfigurationError(f"MCP server {name} command must be a string")
    raw_args = raw_server.get("args", [])
    if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
        raise ConfigurationError(f"MCP server {name} args must be a list of strings")
    raw_env = raw_server.get("env", {})
    if not isinstance(raw_env, dict):
        raise ConfigurationError(f"MCP server {name} env must be an object")
    env: dict[str, str] = {}
    for key, value in raw_env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigurationError(f"MCP server {name} env values must be strings")
        env[key] = _expand_env_reference(value, environment=environment)
    raw_disabled = raw_server.get("disabled", False)
    if not isinstance(raw_disabled, bool):
        raise ConfigurationError(f"MCP server {name} disabled must be a boolean")
    return McpServerConfig(
        name=name,
        type=cast(McpTransportType, server_type),
        command=command,
        args=tuple(cast(Sequence[str], raw_args)),
        env=env,
        disabled=raw_disabled,
    )


def _expand_env_reference(value: str, *, environment: Mapping[str, str]) -> str:
    if not value.startswith("${") or not value.endswith("}"):
        return value
    key = value[2:-1]
    if key not in environment or not environment[key]:
        raise ConfigurationError(f"MCP environment variable is not set: {key}")
    return environment[key]


def _truncate_description(description: str, max_chars: int) -> str:
    if max_chars < 4:
        raise ConfigurationError("mcp_max_description_chars must be >= 4")
    if len(description) <= max_chars:
        return description
    return description[: max_chars - 3] + "..."


def _format_mcp_content(content: object) -> str:
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                text_parts.append(str(item["text"]))
        if text_parts:
            return "\n".join(text_parts)
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def _require_stream(stream: IO[str] | None, name: str) -> IO[str]:
    if stream is None:
        raise RuntimeError(f"MCP process missing {name}")
    return stream
