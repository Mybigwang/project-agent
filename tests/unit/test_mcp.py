from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from project_agent.errors import ConfigurationError
from project_agent.runtime.mcp import (
    McpServerConfig,
    McpStdioClient,
    McpTool,
    build_github_mcp_config,
    build_mcp_tool_name,
    load_mcp_config,
)


def test_build_mcp_tool_name_uses_stable_namespace() -> None:
    assert build_mcp_tool_name("github", "list_issues") == "mcp__github__list_issues"


def test_load_mcp_config_reads_servers_and_expands_env(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp-servers.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
                        "disabled": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(
        config_path=config_path,
        environment={"GITHUB_TOKEN": "secret-token"},
    )

    assert config.servers == {
        "github": McpServerConfig(
            name="github",
            type="stdio",
            command="npx",
            args=("-y", "@modelcontextprotocol/server-github"),
            env={"GITHUB_TOKEN": "secret-token"},
            disabled=False,
        )
    }


def test_load_mcp_config_rejects_missing_env_reference(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp-servers.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"],
                        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="GITHUB_TOKEN"):
        load_mcp_config(config_path=config_path, environment={})


def test_build_github_mcp_config_uses_token_reference() -> None:
    config = build_github_mcp_config()

    assert config["mcpServers"]["github"]["command"] == "npx"
    assert config["mcpServers"]["github"]["args"] == [
        "-y",
        "@modelcontextprotocol/server-github",
    ]
    assert config["mcpServers"]["github"]["env"] == {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
    }


def test_mcp_client_lists_tools_over_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(
        responses=[
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "fake-github", "version": "1.0.0"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {
                            "name": "list_issues",
                            "description": "x" * 2050,
                            "inputSchema": {
                                "type": "object",
                                "properties": {"owner": {"type": "string"}},
                            },
                        }
                    ]
                },
            },
        ]
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: process)

    client = McpStdioClient(
        McpServerConfig(
            name="github",
            type="stdio",
            command="npx",
            args=("-y", "@modelcontextprotocol/server-github"),
            env={"GITHUB_TOKEN": "secret"},
        )
    )

    tools = client.list_tools()

    assert tools[0].name == "mcp__github__list_issues"
    assert tools[0].server_name == "github"
    assert tools[0].remote_name == "list_issues"
    assert tools[0].description.endswith("...")
    assert len(tools[0].description) == 2048
    assert tools[0].input_schema["properties"] == {"owner": {"type": "string"}}
    assert json.loads(process.stdin.writes[0])["method"] == "initialize"
    assert json.loads(process.stdin.writes[1])["method"] == "tools/list"


def test_mcp_tool_invokes_remote_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _FakeProcess(
        responses=[
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [{"type": "text", "text": "issue #1"}],
                    "isError": False,
                },
            },
        ]
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_, **__: process)
    client = McpStdioClient(
        McpServerConfig(
            name="github",
            type="stdio",
            command="npx",
            args=("-y", "@modelcontextprotocol/server-github"),
            env={"GITHUB_TOKEN": "secret"},
        )
    )
    tool = McpTool(
        name="mcp__github__list_issues",
        description="List issues",
        input_schema={"type": "object"},
        server_name="github",
        remote_name="list_issues",
        client=client,
    )

    result = tool.run(
        workspace_root=tmp_path,
        arguments={"owner": "openai", "repo": "codex"},
    )

    assert result.content == "issue #1"
    assert result.data == {"server": "github", "tool": "list_issues"}
    payload = json.loads(process.stdin.writes[0])
    assert payload["method"] == "tools/call"
    assert payload["params"] == {
        "name": "list_issues",
        "arguments": {"owner": "openai", "repo": "codex"},
    }


def test_mcp_tool_returns_json_content_when_non_text(tmp_path: Path) -> None:
    client = _FakeMcpClient(
        response={
            "content": [{"type": "image", "data": "abc"}],
            "isError": False,
        }
    )
    tool = McpTool(
        name="mcp__github__get_asset",
        description="Get asset",
        input_schema={"type": "object"},
        server_name="github",
        remote_name="get_asset",
        client=client,
    )

    result = tool.run(workspace_root=tmp_path, arguments={})

    assert result.content == '[{"data": "abc", "type": "image"}]'


class _FakeStream:
    def __init__(self, lines: list[str] | None = None) -> None:
        self._lines = list(lines or [])
        self.writes: list[str] = []

    def write(self, value: str) -> int:
        self.writes.append(value.strip())
        return len(value)

    def flush(self) -> None:
        return None

    def readline(self) -> str:
        if not self._lines:
            return ""
        return self._lines.pop(0)

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, *, responses: list[dict[str, object]]) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream(
            [json.dumps(response, ensure_ascii=False) + "\n" for response in responses]
        )
        self.stderr = _FakeStream()
        self.returncode = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0


class _FakeMcpClient:
    def __init__(self, *, response: dict[str, object]) -> None:
        self._response = response

    def call_tool(self, *, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        del tool_name, arguments
        return self._response
