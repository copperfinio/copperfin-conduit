"""Tests for Anthropic SSE to Chat Completions adaptation."""

from __future__ import annotations

import json

from app.anthropic.openai_response_adapter import adapt_anthropic_sse_to_chat_sse


def _events(chunks: list[bytes]) -> list[dict]:
    out: list[dict] = []
    for raw in b"".join(chunks).split(b"\n\n"):
        if not raw.startswith(b"data: "):
            continue
        data = raw.removeprefix(b"data: ").decode()
        if data == "[DONE]":
            continue
        out.append(json.loads(data))
    return out


def test_anthropic_text_stream_maps_to_chat_chunks():
    """Text deltas and usage become OpenAI-compatible SSE chunks."""
    chunks = [
        b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":10,"cache_read_input_tokens":5}}}\n\n',
        b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello"}}\n\n',
        b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2,"cache_creation_input_tokens":3}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]

    events = _events(list(adapt_anthropic_sse_to_chat_sse(chunks, model="claude-opus-4-8")))

    assert events[0]["choices"][0]["delta"]["content"] == "hello"
    assert events[1]["choices"][0]["finish_reason"] == "stop"
    assert events[2]["usage"]["prompt_tokens"] == 18
    assert events[2]["usage"]["prompt_tokens_details"]["cached_tokens"] == 5


def test_anthropic_tool_stream_maps_to_chat_tool_call_chunks():
    """Anthropic streaming tool calls become OpenAI tool_call deltas."""
    chunks = [
        b'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"read_file","input":{}}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":"}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\\"README.md\\"}"}}\n\n',
        b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":12}}\n\n',
    ]

    events = _events(list(adapt_anthropic_sse_to_chat_sse(chunks, model="claude-opus-4-8")))

    first = events[0]["choices"][0]["delta"]["tool_calls"][0]
    assert first["id"] == "toolu_1"
    assert first["function"]["name"] == "read_file"
    assert events[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == '{"path":'
    assert events[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"] == '"README.md"}'
    assert events[3]["choices"][0]["finish_reason"] == "tool_calls"
