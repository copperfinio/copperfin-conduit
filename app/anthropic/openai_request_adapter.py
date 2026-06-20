"""OpenAI-compatible Chat Completions to Anthropic Messages adaptation."""

from __future__ import annotations

import base64
import json
from typing import Any

from .request_adapter import (
    AnthropicRequestAdapter,
    UnsupportedAnthropicShape,
)
from .settings import AnthropicSettings

_DEFAULT_MAX_TOKENS = 8192


class AnthropicOpenAIRequestAdapter:
    """Convert Cursor OpenAI-compatible requests to Anthropic Messages."""

    def __init__(self, settings: AnthropicSettings):
        """Initialize the adapter with Anthropic settings."""
        self.settings = settings

    def adapt(self, path: str, payload: dict[str, Any]):
        """Adapt a Chat Completions request for Anthropic upstream."""
        clean_path = path.strip("/")
        if clean_path not in {"chat/completions", "v1/chat/completions"}:
            raise UnsupportedAnthropicShape(
                f"Unsupported OpenAI-compatible Claude path {path!r}; "
                "expected /v1/chat/completions."
            )
        if not isinstance(payload, dict):
            raise UnsupportedAnthropicShape("Claude request body must be a JSON object.")
        native = self._chat_to_messages(payload)
        return AnthropicRequestAdapter(self.settings).adapt("/v1/messages", native)

    def _chat_to_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise UnsupportedAnthropicShape(
                "Chat Completions payload must include messages."
            )

        system_blocks: list[dict[str, Any]] = []
        anthropic_messages: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role in {"system", "developer"}:
                text = _content_to_text(content)
                if text:
                    system_blocks.append({"type": "text", "text": text})
                continue
            if role == "tool":
                tool_call_id = message.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id:
                    anthropic_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call_id,
                                    "content": _content_to_text(content),
                                }
                            ],
                        }
                    )
                continue
            if role == "user":
                blocks = _content_to_anthropic_blocks(content, role="user")
                if blocks:
                    anthropic_messages.append({"role": "user", "content": blocks})
                continue
            if role == "assistant":
                blocks = _content_to_anthropic_blocks(content, role="assistant")
                for tool_call in message.get("tool_calls") or []:
                    block = _tool_call_to_block(tool_call)
                    if block is not None:
                        blocks.append(block)
                if blocks:
                    anthropic_messages.append(
                        {"role": "assistant", "content": blocks}
                    )

        body: dict[str, Any] = {
            "model": payload.get("model"),
            "messages": anthropic_messages,
            "stream": True,
            "max_tokens": _max_tokens(payload),
        }
        if system_blocks:
            body["system"] = system_blocks
        tools = _tools_to_anthropic(payload.get("tools"))
        if tools:
            body["tools"] = tools
        tool_choice = _tool_choice_to_anthropic(payload.get("tool_choice"))
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            body["metadata"] = metadata
        elif isinstance(payload.get("user"), str):
            body["metadata"] = {"user_id": payload["user"]}
        return body


def _max_tokens(payload: dict[str, Any]) -> int:
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return _DEFAULT_MAX_TOKENS


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(f"[{item.get('type', 'unknown')}]")
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _content_to_anthropic_blocks(content: Any, *, role: str) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}]
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            blocks.append({"type": "text", "text": str(part)})
            continue
        part_type = part.get("type")
        if part_type in {"text", "input_text", "output_text"}:
            text = str(part.get("text", ""))
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if role == "user" and part_type in {"image_url", "input_image"}:
            image = _image_part_to_anthropic(part)
            if image is not None:
                blocks.append(image)
    return blocks


def _image_part_to_anthropic(part: dict[str, Any]) -> dict[str, Any] | None:
    image_url = part.get("image_url")
    if isinstance(image_url, dict):
        url = image_url.get("url")
    else:
        url = image_url
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media_type = header.removeprefix("data:").split(";", 1)[0]
        if not media_type:
            media_type = "image/png"
        try:
            base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            return None
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _tool_call_to_block(tool_call: Any) -> dict[str, Any] | None:
    if not isinstance(tool_call, dict):
        return None
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    return {
        "type": "tool_use",
        "id": str(tool_call.get("id") or ""),
        "name": name,
        "input": _parse_tool_arguments(function.get("arguments")),
    }


def _parse_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tools_to_anthropic(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            schema = function.get("parameters")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            out.append(
                {
                    "name": name,
                    "description": function.get("description") or "",
                    "input_schema": schema,
                }
            )
        elif isinstance(tool.get("name"), str):
            out.append(dict(tool))
    return out


def _tool_choice_to_anthropic(tool_choice: Any) -> dict[str, Any] | None:
    if tool_choice is None or tool_choice == "auto":
        return None
    if isinstance(tool_choice, str):
        if tool_choice == "none":
            return {"type": "none"}
        if tool_choice in {"required", "any"}:
            return {"type": "any"}
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            function = tool_choice.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                return {"type": "tool", "name": function["name"]}
        if tool_choice.get("type") in {"auto", "any", "none", "tool"}:
            return dict(tool_choice)
    return None
