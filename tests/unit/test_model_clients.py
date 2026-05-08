from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Any

import pytest

import project_agent.runtime.model_clients as model_clients
from project_agent.core.types import Message, SkillCall, ToolCall
from project_agent.errors import AgentError
from project_agent.runtime.model_clients import OpenAICompatibleModelClient


@dataclass(frozen=True)
class _ToolStub:
    name: str = "echo"
    description: str = "Echo content"
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        }
    )
    is_read_only: bool = True


def _allow_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )


class _FakeHTTPResponse:
    def __init__(
        self,
        *,
        status: int,
        payload: dict[str, object],
        raw_body: bytes | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self._raw_body = raw_body
        self._line_offset = 0

    def read(self, size: int | None = None) -> bytes:
        body = self._body()
        if size is None:
            return body
        return body[:size]

    def readline(self, size: int = -1) -> bytes:
        body = self._body()
        if self._line_offset >= len(body):
            return b""
        next_newline = body.find(b"\n", self._line_offset)
        end_offset = len(body) if next_newline == -1 else next_newline + 1
        if size >= 0:
            end_offset = min(end_offset, self._line_offset + size)
        line = body[self._line_offset : end_offset]
        self._line_offset = end_offset
        return line

    def _body(self) -> bytes:
        if self._raw_body is not None:
            return self._raw_body
        return json.dumps(self._payload).encode("utf-8")


class _FakeConnection:
    captured: dict[str, Any] = {}
    status = 200
    payload: dict[str, object] = {
        "choices": [{"message": {"role": "assistant", "content": "real response"}}]
    }
    raw_body: bytes | None = None
    request_error: OSError | None = None

    def __init__(self, **kwargs: object) -> None:
        self.captured = {"init": kwargs}
        _FakeConnection.captured = self.captured

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        if self.request_error is not None:
            raise self.request_error
        self.captured.update(
            {
                "method": method,
                "path": path,
                "body": json.loads(body.decode("utf-8")),
                "headers": headers,
            }
        )

    def close(self) -> None:
        self.captured["closed"] = True

    def getresponse(self) -> _FakeHTTPResponse:
        return _FakeHTTPResponse(
            status=self.status,
            payload=self.payload,
            raw_body=self.raw_body,
        )


def _stream_event(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _stream_body_from_events(events: tuple[str, ...]) -> bytes:
    return "".join(events).encode("utf-8")


@pytest.fixture(autouse=True)
def reset_fake_connection() -> None:
    _FakeConnection.captured = {}
    _FakeConnection.status = 200
    _FakeConnection.payload = {
        "choices": [{"message": {"role": "assistant", "content": "real response"}}]
    }
    _FakeConnection.raw_body = None
    _FakeConnection.request_error = None


def _patch_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_clients, "_PinnedHTTPSConnection", _FakeConnection)


def _make_client(monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleModelClient:
    _allow_public_host(monkeypatch)
    _patch_connection(monkeypatch)
    return OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
    )


def test_openai_compatible_model_client_posts_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)

    response = client.complete(
        messages=(Message(role="user", content="hello"),),
        tools=(),
    )

    assert response == Message(role="assistant", content="real response")
    assert _FakeConnection.captured["init"]["base_url"].connection_host == "93.184.216.34"
    assert _FakeConnection.captured["init"]["timeout"] == 600.0
    assert _FakeConnection.captured["method"] == "POST"
    assert _FakeConnection.captured["path"] == "/v1/chat/completions"
    assert _FakeConnection.captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "Host": "model.example",
    }
    assert _FakeConnection.captured["body"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_openai_compatible_model_client_streams_content_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = _stream_body_from_events(
        (
            _stream_event({"choices": [{"delta": {"role": "assistant"}}]}),
            "\n",
            _stream_event({"choices": [{"delta": {"content": "hello"}}]}),
            _stream_event({"choices": [{"delta": {"content": " world"}}]}),
            "data: [DONE]\n\n",
        )
    )
    client = _make_client(monkeypatch)

    chunks = tuple(
        client.stream_complete(messages=(Message(role="user", content="hello"),), tools=())
    )

    assert chunks == ("hello", " world")
    assert _FakeConnection.captured["body"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }


def test_openai_compatible_model_client_streams_with_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = _stream_body_from_events(
        (
            _stream_event({"choices": [{"delta": {"content": "use"}}]}),
            "data: [DONE]\n\n",
        )
    )
    client = _make_client(monkeypatch)

    chunks = tuple(
        client.stream_complete(
            messages=(Message(role="user", content="use a tool"),),
            tools=(_ToolStub(),),
        )
    )

    assert chunks == ("use",)
    assert _FakeConnection.captured["body"]["stream"] is True
    assert _FakeConnection.captured["body"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo content",
                "parameters": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
        }
    ]


def test_openai_compatible_model_client_stream_sanitizes_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.status = 524
    _FakeConnection.raw_body = b"sensitive test-key details"
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError) as error:
        tuple(client.stream_complete(messages=(Message(role="user", content="hello"),), tools=()))

    assert str(error.value) == "model request failed with HTTP 524"
    assert "test-key" not in str(error.value)


def test_openai_compatible_model_client_stream_sanitizes_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.request_error = OSError("internal proxy details")
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError) as error:
        tuple(client.stream_complete(messages=(Message(role="user", content="hello"),), tools=()))

    assert str(error.value) == "model request failed due to a network error"
    assert "internal proxy details" not in str(error.value)


def test_openai_compatible_model_client_stream_rejects_invalid_json_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = b"data: not-json\n\n"
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="valid JSON"):
        tuple(client.stream_complete(messages=(Message(role="user", content="hello"),), tools=()))


def test_openai_compatible_model_client_stream_rejects_missing_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = _stream_body_from_events(
        (_stream_event({"choices": [{"message": {"content": "hello"}}]}),)
    )
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="missing delta"):
        tuple(client.stream_complete(messages=(Message(role="user", content="hello"),), tools=()))


def test_openai_compatible_model_client_adds_tool_choice_when_tools_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)

    client.complete(
        messages=(Message(role="user", content="use a tool"),),
        tools=(_ToolStub(),),
    )

    assert _FakeConnection.captured["body"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo content",
                "parameters": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
        }
    ]
    assert _FakeConnection.captured["body"]["tool_choice"] == "auto"


def test_openai_compatible_model_client_serializes_tool_call_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)

    client.complete(
        messages=(
            Message(role="user", content="use a tool"),
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),
                ),
            ),
            Message(role="tool", content="echo: ping", tool_call_id="call_123"),
        ),
        tools=(_ToolStub(),),
    )

    serialized_messages = _FakeConnection.captured["body"]["messages"]
    assert serialized_messages[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"content": "ping"}'},
            }
        ],
    }
    assert serialized_messages[2] == {
        "role": "tool",
        "content": "echo: ping",
        "tool_call_id": "call_123",
    }


def test_openai_compatible_model_client_serializes_tool_call_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(monkeypatch)

    client.complete(
        messages=(
            Message(
                role="assistant",
                content="calling echo",
                tool_calls=(
                    ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),
                ),
            ),
        ),
        tools=(),
    )

    serialized_message = _FakeConnection.captured["body"]["messages"][0]
    assert serialized_message["content"] == "calling echo"


def test_openai_compatible_model_client_rejects_tool_call_with_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "calling echo",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "echo", "arguments": '{"content": "ping"}'},
                        }
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="must not include content with tool_calls"):
        client.complete(
            messages=(Message(role="user", content="use a tool"),), tools=(_ToolStub(),)
        )


def test_openai_compatible_model_client_parses_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "arguments": '{"content": "ping"}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    response = client.complete(
        messages=(Message(role="user", content="use a tool"),),
        tools=(_ToolStub(),),
    )

    assert response == (ToolCall(name="echo", arguments={"content": "ping"}, call_id="call_123"),)


def test_openai_compatible_model_client_parses_multiple_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "index.html"}',
                            },
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path": "index.html", "content": "updated"}',
                            },
                        },
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    response = client.complete(
        messages=(Message(role="user", content="use tools"),),
        tools=(_ToolStub(),),
    )

    assert response == (
        ToolCall(name="read_file", arguments={"path": "index.html"}, call_id="call_1"),
        ToolCall(
            name="write_file",
            arguments={"path": "index.html", "content": "updated"},
            call_id="call_2",
        ),
    )

def test_openai_compatible_model_client_rejects_duplicate_tool_call_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path": "a"}'},
                        },
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "write_file", "arguments": '{"path": "b"}'},
                        },
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="tool call ids must be unique"):
        client.complete(
            messages=(Message(role="user", content="use tools"),),
            tools=(_ToolStub(),),
        )


def test_openai_compatible_model_client_rejects_too_many_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": f"call_{index}",
                            "type": "function",
                            "function": {"name": "echo", "arguments": "{}"},
                        }
                        for index in range(model_clients.MAX_TOOL_CALLS_PER_RESPONSE + 1)
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="too many tool calls"):
        client.complete(
            messages=(Message(role="user", content="use tools"),),
            tools=(_ToolStub(),),
        )


def test_openai_compatible_model_client_rejects_invalid_tool_call_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "arguments": "not-json",
                            },
                        }
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="arguments must be valid JSON"):
        client.complete(
            messages=(Message(role="user", content="use a tool"),),
            tools=(_ToolStub(),),
        )


def test_openai_compatible_model_client_rejects_malformed_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_call = {
        "type": "function",
        "function": {"name": "echo", "arguments": '{"content": "ping"}'},
    }
    _FakeConnection.payload = {
        "choices": [{"message": {"role": "assistant", "tool_calls": [tool_call, tool_call]}}]
    }
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="missing id"):
        client.complete(
            messages=(Message(role="user", content="use a tool"),),
            tools=(_ToolStub(),),
        )


def test_openai_compatible_model_client_sanitizes_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.status = 401
    _FakeConnection.payload = {"error": "sensitive test-key details"}
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError) as error:
        client.complete(messages=(Message(role="user", content="hello"),), tools=())

    assert str(error.value) == "model request failed with HTTP 401"
    assert "test-key" not in str(error.value)


def test_openai_compatible_model_client_sanitizes_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.request_error = OSError("internal proxy details")
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError) as error:
        client.complete(messages=(Message(role="user", content="hello"),), tools=())

    assert str(error.value) == "model request failed due to a network error"
    assert "internal proxy details" not in str(error.value)


def test_openai_compatible_model_client_rejects_non_function_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "custom",
                            "function": {
                                "name": "echo",
                                "arguments": '{"content": "ping"}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="type must be function"):
        client.complete(
            messages=(Message(role="user", content="use a tool"),),
            tools=(_ToolStub(),),
        )


def test_openai_compatible_model_client_rejects_invalid_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = b"not-json"
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="valid JSON"):
        client.complete(messages=(Message(role="user", content="hello"),), tools=())


def test_openai_compatible_model_client_rejects_large_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = b"x" * (model_clients.MAX_MODEL_RESPONSE_BYTES + 1)
    client = _make_client(monkeypatch)

    with pytest.raises(AgentError, match="exceeded maximum size"):
        client.complete(messages=(Message(role="user", content="hello"),), tools=())


@pytest.mark.parametrize(
    "base_url",
    [
        "http://model.example/v1",
        "https://user:pass@model.example/v1",
        "https://model.example/v1?x=1",
        "https://model.example/v1#fragment",
        "https://model.example:abc/v1",
    ],
)
def test_openai_compatible_model_client_rejects_invalid_base_url(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    _allow_public_host(monkeypatch)

    with pytest.raises(AgentError):
        OpenAICompatibleModelClient(
            base_url=base_url,
            api_key="test-key",
            model="test-model",
        )


def test_openai_compatible_model_client_uses_later_public_dns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                ("127.0.0.1", 443),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                ("93.184.216.34", 443),
            ),
        ],
    )
    _patch_connection(monkeypatch)

    client = OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
    )

    client.complete(messages=(Message(role="user", content="hello"),), tools=())

    assert _FakeConnection.captured["init"]["base_url"].connection_host == "93.184.216.34"




def test_openai_compatible_model_client_stream_parses_skill_call_without_streaming_raw_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.raw_body = _stream_body_from_events(
        (
            _stream_event(
                {
                    "choices": [
                        {
                            "delta": {
                                "content": '{"skill":{"name":"debug-bug","arguments":"index"}}'
                            }
                        }
                    ]
                }
            ),
            "data: [DONE]\n\n",
        )
    )
    client = _make_client(monkeypatch)
    streamed_chunks: list[str] = []

    response = client.complete(
        messages=(Message(role="user", content="debug index"),),
        tools=(),
        stream_callback=streamed_chunks.append,
    )

    assert response == SkillCall(name="debug-bug", raw_args="index")
    assert streamed_chunks == []


def test_openai_compatible_model_client_preserves_plain_text_when_skill_payload_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"skill":{"name":"","arguments":"src/app.py"}}',
                }
            }
        ]
    }
    client = _make_client(monkeypatch)

    response = client.complete(messages=(Message(role="user", content="review this"),), tools=())

    assert response == Message(
        role="assistant",
        content='{"skill":{"name":"","arguments":"src/app.py"}}',
    )


def test_openai_compatible_model_client_rejects_private_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                ("127.0.0.1", 443),
            )
        ],
    )

    with pytest.raises(AgentError, match="public IP"):
        OpenAICompatibleModelClient(
            base_url="https://localhost/v1",
            api_key="test-key",
            model="test-model",
        )
