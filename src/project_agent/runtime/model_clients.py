from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from project_agent.core.interfaces import StreamingModelClient, Tool
from project_agent.core.types import Message, ToolCall
from project_agent.errors import AgentError

MAX_MODEL_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class _ValidatedBaseUrl:
    host: str
    host_header: str
    connection_host: str
    port: int
    path: str


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        *,
        base_url: _ValidatedBaseUrl,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(
            host=base_url.host,
            port=base_url.port,
            timeout=timeout,
            context=context,
        )
        self._connection_host = base_url.connection_host
        self._ssl_context = context

    def connect(self) -> None:
        sock = socket.create_connection((self._connection_host, self.port), self.timeout)
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


class OpenAICompatibleModelClient(StreamingModelClient):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.name = model
        self._base_url = _validate_base_url(base_url)
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Message | ToolCall:
        payload: dict[str, Any] = {
            "model": self.name,
            "messages": tuple(_serialize_message(message) for message in messages),
        }
        serialized_tools = _serialize_tools(tools)
        if serialized_tools:
            payload = {**payload, "tools": serialized_tools, "tool_choice": "auto"}
        raw_response = self._post_chat_completions(payload)
        return _parse_chat_response(raw_response)

    def stream_complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Iterable[str]:
        response = self.complete(messages=messages, tools=tools)
        if isinstance(response, ToolCall):
            return ()
        return (response.content,)

    def _post_chat_completions(self, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8")
        path = f"{self._base_url.path}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Host": self._base_url.host_header,
        }
        try:
            context = ssl.create_default_context()
            connection = _PinnedHTTPSConnection(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                context=context,
            )
            try:
                connection.request("POST", path, body=body, headers=headers)
                response = connection.getresponse()
                response_body = response.read(MAX_MODEL_RESPONSE_BYTES + 1)
            finally:
                connection.close()
        except OSError as error:
            raise AgentError("model request failed due to a network error") from error

        if response.status >= 400:
            raise AgentError(f"model request failed with HTTP {response.status}")

        if len(response_body) > MAX_MODEL_RESPONSE_BYTES:
            raise AgentError("model response exceeded maximum size")

        try:
            parsed = json.loads(response_body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise AgentError("model response must be valid JSON") from error
        if not isinstance(parsed, dict):
            raise AgentError("model response must be a JSON object")
        return parsed


class MockModelClient(StreamingModelClient):
    name = "mock-model"

    def complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Message | ToolCall:
        user_message = self._last_message(messages, role="user")
        tool_message = self._find_last_message(messages, role="tool")
        turn = self._turn_count(messages)

        if user_message.content == "loop forever":
            return ToolCall(name="echo", arguments={"content": "loop"})
        if user_message.content == "missing tool" and tool_message is None:
            return ToolCall(name="missing", arguments={})
        if user_message.content == "boom tool" and tool_message is None:
            return ToolCall(name="boom", arguments={})
        if user_message.content.startswith("use tool ") and tool_message is None:
            return ToolCall(
                name="echo", arguments={"content": user_message.content.removeprefix("use tool ")}
            )
        if tool_message is not None:
            return Message(
                role="assistant",
                content=f"Tool result (turn {turn}): {self._tool_payload(tool_message)}",
            )
        return Message(
            role="assistant", content=f"Mock response (turn {turn}): {user_message.content}"
        )

    def stream_complete(
        self,
        *,
        messages: Sequence[Message],
        tools: Sequence[Tool],
    ) -> Iterable[str]:
        response = self.complete(messages=messages, tools=tools)
        if isinstance(response, ToolCall):
            return ()
        return tuple(response.content.split())

    def _find_last_message(self, messages: Sequence[Message], *, role: str) -> Message | None:
        for message in reversed(messages):
            if message.role == role:
                return message
        return None

    def _last_message(self, messages: Sequence[Message], *, role: str) -> Message:
        message = self._find_last_message(messages, role=role)
        if message is None:
            raise ValueError(f"missing message for role={role}")
        return message

    def _tool_payload(self, tool_message: Message) -> str:
        payload = json.loads(tool_message.content)
        content = payload["content"]
        if not isinstance(content, str):
            raise ValueError("tool payload content must be a string")
        return content

    def _turn_count(self, messages: Sequence[Message]) -> int:
        return sum(1 for message in messages if message.role == "user")


def _serialize_message(message: Message) -> dict[str, object]:
    serialized: dict[str, object] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        serialized = {
            **serialized,
            "content": message.content or None,
            "tool_calls": [_serialize_tool_call(tool_call) for tool_call in message.tool_calls],
        }
    if message.tool_call_id is not None:
        serialized = {**serialized, "tool_call_id": message.tool_call_id}
    return serialized


def _serialize_tool_call(tool_call: ToolCall) -> dict[str, object]:
    if tool_call.call_id is None:
        raise AgentError("tool call id is required")
    return {
        "id": tool_call.call_id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
        },
    }


def _serialize_tools(tools: Sequence[Tool]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    )


def _validate_base_url(base_url: str) -> _ValidatedBaseUrl:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https":
        raise AgentError("model_base_url must use https")
    if parsed.username or parsed.password:
        raise AgentError("model_base_url must not include credentials")
    if parsed.query or parsed.fragment:
        raise AgentError("model_base_url must not include query or fragment")
    if not parsed.hostname:
        raise AgentError("model_base_url must include a host")
    try:
        port = parsed.port or 443
    except ValueError as error:
        raise AgentError("model_base_url port must be valid") from error
    connection_host = _resolve_public_host(parsed.hostname)
    path = parsed.path.rstrip("/") or ""
    host_header = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{port}"
    return _ValidatedBaseUrl(
        host=parsed.hostname,
        host_header=host_header,
        connection_host=connection_host,
        port=port,
        path=path,
    )


def _resolve_public_host(host: str) -> str:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise AgentError("model_base_url host could not be resolved") from error

    for address_info in addresses:
        socket_address = address_info[4]
        address = ipaddress.ip_address(socket_address[0])
        if address.is_global:
            return str(address)
    raise AgentError("model_base_url host must resolve to a public IP address")


def _parse_chat_response(response: dict[str, object]) -> Message | ToolCall:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AgentError("model response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise AgentError("model response choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise AgentError("model response choice missing message")

    tool_call = _parse_tool_call(message)
    if tool_call is not None:
        content = message.get("content")
        if content not in (None, ""):
            raise AgentError("model response must not include content with tool_calls")
        return tool_call

    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise AgentError("model response message content must be a string")
    return Message(role="assistant", content=content)


def _parse_tool_call(message: dict[object, object]) -> ToolCall | None:
    tool_calls = message.get("tool_calls")
    if tool_calls is None:
        return None
    if not isinstance(tool_calls, list) or not tool_calls:
        raise AgentError("model response tool_calls must be a non-empty list")
    if len(tool_calls) > 1:
        raise AgentError("model response returned multiple tool calls")

    first_tool_call = tool_calls[0]
    if not isinstance(first_tool_call, dict):
        raise AgentError("model response tool call must be an object")
    call_id = first_tool_call.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise AgentError("model response tool call missing id")
    tool_call_type = first_tool_call.get("type")
    if tool_call_type != "function":
        raise AgentError("model response tool call type must be function")
    function = first_tool_call.get("function")
    if not isinstance(function, dict):
        raise AgentError("model response tool call missing function")
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise AgentError("model response tool call function missing name")
    raw_arguments = function.get("arguments", "{}")
    if not isinstance(raw_arguments, str):
        raise AgentError("model response tool call arguments must be a string")
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as error:
        raise AgentError("model response tool call arguments must be valid JSON") from error
    if not isinstance(arguments, dict):
        raise AgentError("model response tool call arguments must be a JSON object")
    return ToolCall(name=name, arguments=arguments, call_id=call_id)
