"""Anthropic Messages SSE to Chat Completions SSE adaptation."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from string import ascii_letters, digits
from typing import Any, Iterable, Iterator

from ..codex.response_adapter import SSEDecoder, SSEEvent
from ..dashboard.telemetry import telemetry


@dataclass
class _ToolCallState:
    index: int
    name: str


class AnthropicChatSSEAdapter:
    """Translate Anthropic Messages SSE into Chat Completions chunks."""

    def __init__(self, model: str, telemetry_id: str = ""):
        """Initialize stream state for one chat response."""
        self.model = model
        self.telemetry_id = telemetry_id
        self.chat_id = _chat_completion_id()
        self.blocks: dict[int, str] = {}
        self.tool_blocks: dict[int, _ToolCallState] = {}
        self.tool_calls = 0
        self.usage: dict[str, Any] = {}
        self.stop_reason: str | None = None

    def handle(self, event: SSEEvent) -> list[dict[str, Any]]:
        """Handle one upstream SSE event."""
        event_name = event.event or ""
        obj = event.json
        if not isinstance(obj, dict):
            return []
        event_type = obj.get("type") or event_name
        if event_type == "message_start":
            message = obj.get("message")
            if isinstance(message, dict):
                self._merge_usage(message.get("usage"))
            return []
        if event_type == "content_block_start":
            return self._content_block_start(obj)
        if event_type == "content_block_delta":
            chunk = self._content_block_delta(obj)
            return [chunk] if chunk is not None else []
        if event_type == "message_delta":
            self._message_delta(obj)
            return []
        if event_type == "error":
            return [self._error(obj)]
        return []

    def finish(self) -> list[dict[str, Any]]:
        """Build terminal chunks."""
        finish_reason = _map_stop_reason(self.stop_reason)
        chunks = [self._chunk(finish_reason=finish_reason)]
        usage = self._usage_chunk()
        if usage is not None:
            chunks.append(usage)
        if self.usage:
            _log_usage(self.model, self.usage, self.stop_reason)
            if self.telemetry_id:
                telemetry.record_usage(
                    self.telemetry_id,
                    provider="anthropic",
                    model=self.model,
                    usage=self.usage,
                    stop_reason=self.stop_reason,
                )
        return chunks

    def _chunk(
        self,
        *,
        delta: dict[str, Any] | None = None,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": self.chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta or {},
                    "finish_reason": finish_reason,
                }
            ],
        }

    def _content_block_start(self, obj: dict[str, Any]) -> list[dict[str, Any]]:
        index = obj.get("index")
        block = obj.get("content_block")
        if not isinstance(index, int) or not isinstance(block, dict):
            return []
        block_type = block.get("type")
        if block_type == "text":
            self.blocks[index] = "text"
            return []
        if block_type == "thinking":
            self.blocks[index] = "thinking"
            return []
        if block_type == "tool_use":
            tool_index = self.tool_calls
            self.tool_calls += 1
            name = str(block.get("name") or "")
            self.blocks[index] = "tool_use"
            self.tool_blocks[index] = _ToolCallState(index=tool_index, name=name)
            initial_args = block.get("input")
            arguments = (
                json.dumps(initial_args, separators=(",", ":"))
                if isinstance(initial_args, dict) and initial_args
                else ""
            )
            return [
                self._chunk(
                    delta={
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": tool_index,
                                "id": str(block.get("id") or ""),
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": arguments,
                                },
                            }
                        ],
                    }
                )
            ]
        return []

    def _content_block_delta(self, obj: dict[str, Any]) -> dict[str, Any] | None:
        index = obj.get("index")
        delta = obj.get("delta")
        if not isinstance(index, int) or not isinstance(delta, dict):
            return None
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = str(delta.get("text") or "")
            if text and self.telemetry_id:
                telemetry.record_stream_delta(self.telemetry_id, text=text)
            return self._chunk(delta={"role": "assistant", "content": text})
        if delta_type == "thinking_delta":
            thinking = str(delta.get("thinking") or delta.get("text") or "")
            if thinking and self.telemetry_id:
                telemetry.record_stream_delta(self.telemetry_id, reasoning=thinking)
            return None
        if delta_type == "input_json_delta":
            state = self.tool_blocks.get(index)
            if state is None:
                return None
            partial_json = str(delta.get("partial_json") or "")
            if partial_json and self.telemetry_id:
                telemetry.record_stream_delta(
                    self.telemetry_id, tool_delta=partial_json
                )
            return self._chunk(
                delta={
                    "tool_calls": [
                        {
                            "index": state.index,
                            "function": {"arguments": partial_json},
                        }
                    ]
                }
            )
        return None

    def _message_delta(self, obj: dict[str, Any]) -> None:
        delta = obj.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
            self.stop_reason = delta["stop_reason"]
        self._merge_usage(obj.get("usage"))

    def _merge_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, int | float):
                self.usage[key] = int(value)
            elif isinstance(value, dict):
                self.usage[key] = value

    def _usage_chunk(self) -> dict[str, Any] | None:
        if not self.usage:
            return None
        input_tokens = int(self.usage.get("input_tokens") or 0)
        output_tokens = int(self.usage.get("output_tokens") or 0)
        cache_read = int(self.usage.get("cache_read_input_tokens") or 0)
        cache_write = int(self.usage.get("cache_creation_input_tokens") or 0)
        total_prompt = input_tokens + cache_read + cache_write
        return {
            "id": self.chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.model,
            "choices": [],
            "usage": {
                "prompt_tokens": total_prompt,
                "completion_tokens": output_tokens,
                "total_tokens": total_prompt + output_tokens,
                "prompt_tokens_details": {
                    "cached_tokens": cache_read,
                    "cache_creation_input_tokens": cache_write,
                },
            },
        }

    def _error(self, obj: dict[str, Any]) -> dict[str, Any]:
        error = obj.get("error")
        message = "Anthropic upstream stream error."
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            message = error["message"]
        return self._chunk(delta={"role": "assistant", "content": message})


def adapt_anthropic_sse_to_chat_sse(
    chunks: Iterable[bytes],
    *,
    model: str,
    telemetry_id: str = "",
) -> Iterator[bytes]:
    """Adapt an upstream Anthropic SSE byte stream to Chat Completions SSE."""
    decoder = SSEDecoder()
    adapter = AnthropicChatSSEAdapter(model, telemetry_id)
    for chunk in chunks:
        for event in decoder.feed(chunk):
            for message in adapter.handle(event):
                yield _encode_sse(message)
    for event in decoder.flush():
        for message in adapter.handle(event):
            yield _encode_sse(message)
    for message in adapter.finish():
        yield _encode_sse(message)
    yield b"data: [DONE]\n\n"


def _encode_sse(obj: dict[str, Any]) -> bytes:
    return (
        b"data: "
        + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        + b"\n\n"
    )


def _map_stop_reason(value: str | None) -> str:
    if value == "tool_use":
        return "tool_calls"
    if value == "max_tokens":
        return "length"
    if value == "refusal":
        return "content_filter"
    return "stop"


def _log_usage(model: str, usage: dict[str, Any], stop_reason: str | None) -> None:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    total = input_tokens + output_tokens + cache_read + cache_write
    effective_input = input_tokens + cache_read + cache_write
    cache_pct = (cache_read / effective_input * 100) if effective_input > 0 else 0

    from ..common.logging import console

    console.print(
        f"[bold green]ANTHROPIC USAGE:[/bold green] "
        f"model={model} input={input_tokens} "
        f"cache_read={cache_read} ({cache_pct:.0f}%) "
        f"cache_write={cache_write} output={output_tokens} "
        f"total={total} stop={stop_reason or 'unknown'}"
    )


def _chat_completion_id() -> str:
    alphabet = ascii_letters + digits
    return "chatcmpl-" + "".join(random.choices(alphabet, k=24))
