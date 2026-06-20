"""Unit tests for Fusion panel stream collection."""

from __future__ import annotations

from app.fusion.invoker import (
    FusionTextResult,
    _log_panel_usage,
    collect_anthropic_text,
    collect_codex_text,
)


def test_collect_codex_text_captures_text_and_usage():
    """Codex panel streams expose text plus cached token usage."""
    result = collect_codex_text(
        [
            b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"hel"}\n\n',
            b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"lo"}\n\n',
            b'event: response.completed\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":100,"output_tokens":5,"total_tokens":105,"input_tokens_details":{"cached_tokens":80}}}}\n\n',
        ]
    )

    assert result.text == "hello"
    assert result.stop_reason == "completed"
    assert result.usage == {
        "input_tokens": 100,
        "output_tokens": 5,
        "total_tokens": 105,
        "input_tokens_details": {"cached_tokens": 80},
    }


def test_collect_anthropic_text_captures_text_usage_and_stop_reason():
    """Claude panel streams expose text, cache reads, cache writes, and stop reason."""
    result = collect_anthropic_text(
        [
            b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":10,"cache_creation_input_tokens":4,"cache_read_input_tokens":30}}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"panel "}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}\n\n',
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}}\n\n',
        ]
    )

    assert result.text == "panel ok"
    assert result.stop_reason == "end_turn"
    assert result.usage == {
        "input_tokens": 10,
        "cache_creation_input_tokens": 4,
        "cache_read_input_tokens": 30,
        "output_tokens": 7,
    }


def test_fusion_codex_usage_log_reports_cached_input_percent(monkeypatch):
    """Codex Fusion cache reporting uses cached_tokens / input_tokens."""
    lines = []

    class Console:
        def print(self, message):
            lines.append(message)

    monkeypatch.setattr("app.fusion.invoker.console", Console())

    _log_panel_usage(
        model="cp-gpt55-balanced",
        provider="codex",
        result=FusionTextResult(
            text="panel",
            usage={
                "input_tokens": 137474,
                "output_tokens": 319,
                "total_tokens": 137793,
                "input_tokens_details": {"cached_tokens": 133888},
            },
            stop_reason="completed",
        ),
    )

    assert lines == [
        "[bold green]FUSION USAGE:[/bold green] "
        "model=cp-gpt55-balanced provider=codex input=137474 "
        "cache_read=133888 (97%) cache_write=0 "
        "output=319 total=137793 stop=completed"
    ]


def test_fusion_anthropic_usage_log_reports_cache_read_and_write(monkeypatch):
    """Claude Fusion cache reporting includes read and write cache buckets."""
    lines = []

    class Console:
        def print(self, message):
            lines.append(message)

    monkeypatch.setattr("app.fusion.invoker.console", Console())

    _log_panel_usage(
        model="cp-opus48-xhigh",
        provider="anthropic",
        result=FusionTextResult(
            text="panel",
            usage={
                "input_tokens": 100,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 50,
                "output_tokens": 25,
            },
            stop_reason="end_turn",
        ),
    )

    assert lines == [
        "[bold green]FUSION USAGE:[/bold green] "
        "model=cp-opus48-xhigh provider=anthropic input=100 "
        "cache_read=900 (86%) cache_write=50 "
        "output=25 total=1075 stop=end_turn"
    ]
