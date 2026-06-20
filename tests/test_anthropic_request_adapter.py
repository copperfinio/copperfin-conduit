"""Tests for Anthropic provider request adaptation."""

from __future__ import annotations

from app.anthropic.request_adapter import AnthropicRequestAdapter
from app.anthropic.settings import AnthropicModelProfile


class TestAnthropicSettings:
    """Small settings stand-in for request adapter tests."""

    supported_models = ("claude-opus-4-8", "claude-sonnet-4-6")
    model_profiles = {
        "cp-opus48-xfast": AnthropicModelProfile(
            model="claude-opus-4-8",
            effort="xhigh",
            max_tokens=65536,
            speed="fast",
        )
    }
    cache_control = "auto"
    cache_ttl = "5m"
    thinking_display = "summarized"
    eager_tool_streaming = True


def test_profile_maps_opus_effort_cache_identity_and_sampling_cleanup():
    """Claude aliases map to native Anthropic fields and drop rejected params."""
    adapter = AnthropicRequestAdapter(TestAnthropicSettings())

    adapted = adapter.adapt(
        "/v1/messages",
        {
            "model": "cp-opus48-xfast",
            "messages": [{"role": "user", "content": "ship it"}],
            "system": "Project rules go here.",
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 5,
        },
    )

    body = adapted.body
    assert adapted.inbound_model == "cp-opus48-xfast"
    assert adapted.upstream_model == "claude-opus-4-8"
    assert body["model"] == "claude-opus-4-8"
    assert body["max_tokens"] == 65536
    assert body["speed"] == "fast"
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "xhigh"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["text"] == (
        "You are Claude Code, Anthropic's official CLI for Claude."
    )
    assert body["system"][1]["text"] == "Project rules go here."
    assert body["tools"][0]["eager_input_streaming"] is True
    assert "temperature" not in body
    assert "top_p" not in body
    assert "top_k" not in body


def test_direct_model_keeps_existing_cache_control():
    """Explicit cache settings are preserved for Anthropic-native requests."""
    adapter = AnthropicRequestAdapter(TestAnthropicSettings())

    adapted = adapter.adapt(
        "messages",
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hello"}],
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    )

    assert adapted.body["model"] == "claude-sonnet-4-6"
    assert adapted.body["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert adapted.body["system"][0]["text"].startswith("You are Claude Code")
    assert "thinking" not in adapted.body
