"""Tests for OpenAI-compatible Claude request adaptation."""

from __future__ import annotations

from app.anthropic.openai_request_adapter import AnthropicOpenAIRequestAdapter
from app.anthropic.settings import AnthropicModelProfile


class TestAnthropicSettings:
    """Small settings stand-in for request adapter tests."""

    supported_models = ("claude-opus-4-8",)
    model_profiles = {
        "cp-opus48-ultra": AnthropicModelProfile(
            model="claude-opus-4-8",
            effort="xhigh",
            max_tokens=65536,
        )
    }
    cache_control = "auto"
    cache_ttl = "5m"
    thinking_display = "summarized"
    eager_tool_streaming = True


def test_openai_chat_request_maps_to_anthropic_messages():
    """OpenAI-compatible Cursor requests become Anthropic Messages requests."""
    adapter = AnthropicOpenAIRequestAdapter(TestAnthropicSettings())

    adapted = adapter.adapt(
        "/v1/chat/completions",
        {
            "model": "cp-opus48-ultra",
            "messages": [
                {"role": "system", "content": "Follow project rules."},
                {"role": "user", "content": "Read the file."},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": "read_file"},
            },
            "temperature": 0.2,
        },
    )

    body = adapted.body
    assert adapted.inbound_model == "cp-opus48-ultra"
    assert adapted.upstream_model == "claude-opus-4-8"
    assert body["model"] == "claude-opus-4-8"
    assert body["stream"] is True
    assert body["max_tokens"] == 65536
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Read the file."}]}
    ]
    assert body["system"][0]["text"].startswith("You are Claude Code")
    assert body["system"][1]["text"] == "Follow project rules."
    assert body["tools"][0]["name"] == "read_file"
    assert body["tools"][0]["input_schema"]["required"] == ["path"]
    assert body["tool_choice"] == {"type": "tool", "name": "read_file"}
    assert "temperature" not in body


def test_openai_chat_opus_drops_trailing_assistant_prefill():
    """Cursor assistant prefill is removed before Opus upstream calls."""
    adapter = AnthropicOpenAIRequestAdapter(TestAnthropicSettings())

    adapted = adapter.adapt(
        "/v1/chat/completions",
        {
            "model": "cp-opus48-ultra",
            "messages": [
                {"role": "system", "content": "Follow project rules."},
                {"role": "user", "content": "Continue this task."},
                {"role": "assistant", "content": "Sure"},
            ],
        },
    )

    assert adapted.body["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Continue this task."}],
        }
    ]


def test_openai_tool_results_and_assistant_tool_calls_map_to_anthropic_blocks():
    """Tool-call continuations retain IDs and arguments."""
    adapter = AnthropicOpenAIRequestAdapter(TestAnthropicSettings())

    adapted = adapter.adapt(
        "chat/completions",
        {
            "model": "claude-opus-4-8",
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "toolu_123",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"README.md"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "toolu_123",
                    "content": "contents",
                },
            ],
        },
    )

    assert adapted.body["messages"][0]["content"][0] == {
        "type": "tool_use",
        "id": "toolu_123",
        "name": "read_file",
        "input": {"path": "README.md"},
    }
    assert adapted.body["messages"][1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_123",
        "content": "contents",
    }
