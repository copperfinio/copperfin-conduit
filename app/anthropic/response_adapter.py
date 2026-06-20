"""Anthropic Messages SSE logging helpers."""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from ..codex.response_adapter import SSEDecoder, SSEEvent


class AnthropicUsageLogger:
    """Collect and log Anthropic usage from native SSE events."""

    def __init__(self, model: str):
        """Initialize usage state for a single stream."""
        self.model = model
        self.usage: dict[str, Any] = {}
        self.stop_reason: str | None = None

    def handle(self, event: SSEEvent) -> None:
        """Capture usage fields from one Anthropic SSE event."""
        event_name = event.event or ""
        obj = event.json
        if not isinstance(obj, dict):
            return
        if event_name == "message_start" or obj.get("type") == "message_start":
            message = obj.get("message")
            if isinstance(message, dict):
                self._merge_usage(message.get("usage"))
            return
        if event_name == "message_delta" or obj.get("type") == "message_delta":
            delta = obj.get("delta")
            if isinstance(delta, dict):
                stop_reason = delta.get("stop_reason")
                if isinstance(stop_reason, str):
                    self.stop_reason = stop_reason
            self._merge_usage(obj.get("usage"))
            return
        if event_name == "error" or obj.get("type") == "error":
            from ..common.logging import console

            console.print(f"[bold red]ANTHROPIC STREAM ERROR:[/bold red] {obj}")

    def finish(self) -> None:
        """Log final Anthropic usage, if present."""
        if self.usage:
            _log_usage(self.model, self.usage, self.stop_reason)

    def _merge_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, int | float):
                self.usage[key] = int(value)
            elif isinstance(value, dict):
                self.usage[key] = value


def log_anthropic_sse_usage(
    chunks: Iterable[bytes], *, model: str
) -> Iterator[bytes]:
    """Yield Anthropic SSE chunks while logging cache and token usage."""
    decoder = SSEDecoder()
    logger = AnthropicUsageLogger(model)
    try:
        for chunk in chunks:
            for event in decoder.feed(chunk):
                logger.handle(event)
            yield chunk
        for event in decoder.flush():
            logger.handle(event)
    finally:
        logger.finish()


def _log_usage(model: str, usage: dict[str, Any], stop_reason: str | None) -> None:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    cache_creation = usage.get("cache_creation")
    cache_write_5m = 0
    cache_write_1h = 0
    if isinstance(cache_creation, dict):
        cache_write_5m = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)
        cache_write_1h = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)
    total = input_tokens + output_tokens + cache_read + cache_write
    effective_input = input_tokens + cache_read + cache_write
    cache_pct = (cache_read / effective_input * 100) if effective_input > 0 else 0

    from ..common.logging import console

    console.print(
        f"[bold green]ANTHROPIC USAGE:[/bold green] "
        f"model={model} input={input_tokens} "
        f"cache_read={cache_read} ({cache_pct:.0f}%) "
        f"cache_write={cache_write} "
        f"cache_write_5m={cache_write_5m} cache_write_1h={cache_write_1h} "
        f"output={output_tokens} total={total} stop={stop_reason or 'unknown'}"
    )
