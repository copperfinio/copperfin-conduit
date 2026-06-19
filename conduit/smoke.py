"""Smoke tests for a running Conduit proxy."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from .envfile import load_env


def stream_chat(
    url: str, api_key: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Send a streaming Chat Completions request and return parsed SSE events."""
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        stream=True,
        timeout=90,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"chat request failed: HTTP {response.status_code} {response.text}"
        )

    events: list[dict[str, Any]] = []
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "):
            continue
        data = raw[6:]
        if data == "[DONE]":
            break
        events.append(json.loads(data))
    return events


def text_from_events(events: list[dict[str, Any]]) -> str:
    """Collect text deltas from Chat Completions SSE events."""
    return "".join(
        choice.get("delta", {}).get("content") or ""
        for event in events
        for choice in event.get("choices", [])
    )


def usage_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the final usage payload from SSE events."""
    for event in reversed(events):
        usage = event.get("usage")
        if isinstance(usage, dict):
            return usage
    return {}


def cached_tokens_from_usage(usage: dict[str, Any]) -> int:
    """Return cached input tokens from OpenAI-compatible usage."""
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        details = usage.get("input_tokens_details")
    if not isinstance(details, dict):
        return 0
    value = details.get("cached_tokens")
    return value if isinstance(value, int) else 0


def run_cache_probe(chat_url: str, api_key: str, model: str) -> tuple[int, int]:
    """Run two identical prompts and verify cached tokens on the second."""
    static_prefix = "\n".join(
        (
            f"cache probe static line {index}: "
            "Keep this prefix byte-for-byte stable so prompt caching can match it."
        )
        for index in range(220)
    )
    payload = {
        "model": model,
        "stream": True,
        "reasoning": {"effort": "low"},
        "metadata": {"cursorConversationId": f"cache-probe-{os.getpid()}"},
        "messages": [
            {
                "role": "user",
                "content": static_prefix + "\n\nReply with exactly: OK\n",
            }
        ],
    }

    first_events = stream_chat(chat_url, api_key, payload)
    second_events = stream_chat(chat_url, api_key, payload)
    first_text = text_from_events(first_events)
    second_text = text_from_events(second_events)
    if first_text != "OK" or second_text != "OK":
        raise RuntimeError(
            f"cache probe expected OK twice, got {first_text!r} and {second_text!r}"
        )

    first_cached = cached_tokens_from_usage(usage_from_events(first_events))
    second_cached = cached_tokens_from_usage(usage_from_events(second_events))
    if second_cached <= 0:
        raise RuntimeError(
            "cache probe expected cached tokens on the second identical request, "
            f"got {second_cached}"
        )
    return first_cached, second_cached


def run_smoke(
    *,
    root_url: str,
    api_key: str | None = None,
    model: str = "gpt-5.4-mini",
    cache_probe: bool = False,
    home: Path | None = None,
) -> list[str]:
    """Run Conduit health, model, streaming, tool, and optional cache probes."""
    env = {**load_env(home=home), **os.environ}
    service_key = api_key or env.get("SERVICE_API_KEY")
    if not service_key:
        raise RuntimeError("SERVICE_API_KEY is required via Conduit env or --api-key.")

    root = root_url.rstrip("/")
    provider_url = f"{root}/codex"
    chat_url = f"{provider_url}/v1/chat/completions"
    auth_headers = {"Authorization": f"Bearer {service_key}"}

    health = requests.get(f"{root}/health", timeout=10)
    health.raise_for_status()
    ready = requests.get(f"{provider_url}/ready", headers=auth_headers, timeout=10)
    ready.raise_for_status()
    models = requests.get(f"{provider_url}/v1/models", headers=auth_headers, timeout=10)
    models.raise_for_status()

    text_events = stream_chat(
        chat_url,
        service_key,
        {
            "model": model,
            "stream": True,
            "reasoning": {"effort": "low"},
            "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        },
    )
    text = text_from_events(text_events)
    if text != "pong":
        raise RuntimeError(f"text smoke expected pong, got {text!r}")

    tool_schema = {
        "type": "function",
        "function": {
            "name": "echo_tool",
            "description": "Echoes a short test value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }
    tool_events = stream_chat(
        chat_url,
        service_key,
        {
            "model": model,
            "stream": True,
            "reasoning": {"effort": "low"},
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Call echo_tool with value exactly cursor-proxy-ok. "
                        "Do not answer in plain text."
                    ),
                }
            ],
            "tools": [tool_schema],
            "tool_choice": {"type": "function", "function": {"name": "echo_tool"}},
        },
    )

    tool_name: str | None = None
    tool_args = ""
    finish_reason: str | None = None
    for event in tool_events:
        for choice in event.get("choices", []):
            finish_reason = choice.get("finish_reason") or finish_reason
            for call in choice.get("delta", {}).get("tool_calls", []) or []:
                function = call.get("function", {})
                tool_name = function.get("name") or tool_name
                tool_args += function.get("arguments") or ""
    if tool_name != "echo_tool" or json.loads(tool_args) != {
        "value": "cursor-proxy-ok"
    }:
        raise RuntimeError(f"tool smoke failed: name={tool_name!r} args={tool_args!r}")
    if finish_reason != "tool_calls":
        raise RuntimeError(
            f"tool smoke expected finish_reason=tool_calls, got {finish_reason!r}"
        )

    result_events = stream_chat(
        chat_url,
        service_key,
        {
            "model": model,
            "stream": True,
            "reasoning": {"effort": "low"},
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Call echo_tool with value exactly cursor-proxy-ok, "
                        "then after the tool result reply with the tool value only."
                    ),
                },
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_test_cursor_proxy",
                            "type": "function",
                            "function": {
                                "name": "echo_tool",
                                "arguments": json.dumps({"value": "cursor-proxy-ok"}),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_test_cursor_proxy",
                    "content": json.dumps({"value": "cursor-proxy-ok"}),
                },
            ],
            "tools": [tool_schema],
            "tool_choice": "auto",
        },
    )
    result_text = text_from_events(result_events)
    if result_text != "cursor-proxy-ok":
        raise RuntimeError(
            f"tool result smoke expected cursor-proxy-ok, got {result_text!r}"
        )

    lines = [
        "health=ok",
        "codex_ready=ok",
        "models=ok",
        "text_stream=ok",
        "tool_call_stream=ok",
        "tool_result_stream=ok",
    ]
    if cache_probe:
        first_cached, second_cached = run_cache_probe(chat_url, service_key, model)
        lines.extend(
            [
                f"cache_probe_first_cached_tokens={first_cached}",
                f"cache_probe_second_cached_tokens={second_cached}",
                "cache_probe=ok",
            ]
        )
    return lines
