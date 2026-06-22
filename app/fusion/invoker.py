"""Internal model invocation helpers for Fusion panels."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import requests

from ..anthropic.auth_state import (
    AnthropicAuthManager,
    AnthropicAuthStateError,
    AnthropicAuthStore,
)
from ..anthropic.openai_request_adapter import AnthropicOpenAIRequestAdapter
from ..anthropic.request_adapter import UnsupportedAnthropicShape
from ..anthropic.settings import AnthropicSettings
from ..anthropic.upstream import build_upstream_headers as build_anthropic_headers
from ..anthropic.upstream import post_messages as post_anthropic_messages
from ..codex.auth_state import AuthStateError, CodexAuthManager, CodexAuthStore
from ..codex.request_adapter import CursorRequestAdapter, UnsupportedCursorShape
from ..codex.response_adapter import SSEDecoder
from ..codex.settings import CodexSettings
from ..codex.upstream import build_upstream_headers as build_codex_headers
from ..codex.upstream import post_responses as post_codex_responses
from ..common.logging import console
from ..dashboard.telemetry import telemetry
from .settings import FusionSettings


class FusionInvocationError(RuntimeError):
    """Raised when a Fusion panel model cannot be invoked."""


@dataclass(frozen=True)
class PanelResult:
    """Text result from one Fusion panel model."""

    model: str
    ok: bool
    text: str
    provider: str | None = None
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class FusionTextResult:
    """Collected text and usage from one internal model call."""

    text: str
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None


class FusionModelInvoker:
    """Invoke configured models and collect text-only streaming output."""

    def __init__(
        self,
        *,
        fusion_settings: FusionSettings | None = None,
        codex_settings: CodexSettings | None = None,
        anthropic_settings: AnthropicSettings | None = None,
    ) -> None:
        """Initialize provider settings."""
        self.fusion_settings = fusion_settings or FusionSettings()
        self.codex_settings = codex_settings or CodexSettings()
        self.anthropic_settings = anthropic_settings or AnthropicSettings()

    def invoke_text(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        downstream_headers: dict[str, str],
        phase: str | None = None,
        run_id: str | None = None,
        label: str | None = None,
    ) -> PanelResult:
        """Invoke one model and return collected assistant text."""
        provider = "unknown"
        telemetry_id = ""
        try:
            provider = self.provider_for_model(model)
            telemetry_id = telemetry.record_request_start(
                provider="fusion",
                upstream_provider=provider,
                model=model,
                operation="fusion-panel",
                phase=phase or "panel",
                run_id=run_id,
                label=label,
                payload=payload,
            )
            if provider == "codex":
                result = self._invoke_codex_text(
                    payload=payload,
                    downstream_headers=downstream_headers,
                    telemetry_id=telemetry_id,
                )
            else:
                result = self._invoke_anthropic_text(
                    payload=payload,
                    downstream_headers=downstream_headers,
                    telemetry_id=telemetry_id,
                )
            _log_panel_usage(model=model, provider=provider, result=result)
            console.print(
                "[bold cyan]FUSION PANEL:[/bold cyan] "
                f"model={model} provider={provider} chars={len(result.text)}"
            )
            if telemetry_id:
                telemetry.record_usage(
                    telemetry_id,
                    provider="fusion",
                    usage_provider=provider,
                    model=model,
                    usage=result.usage,
                    stop_reason=result.stop_reason,
                )
                telemetry.record_request_end(telemetry_id, status_code=200)
            return PanelResult(
                model=model,
                ok=True,
                text=result.text,
                provider=provider,
                usage=result.usage,
                stop_reason=result.stop_reason,
            )
        except Exception as exc:  # noqa: B902
            message = str(exc)
            console.print(
                "[bold red]FUSION PANEL FAILED:[/bold red] "
                f"model={model} error={message}"
            )
            if telemetry_id:
                telemetry.record_request_end(
                    telemetry_id, status_code=502, error=message
                )
            return PanelResult(
                model=model,
                ok=False,
                text="",
                provider=provider if provider != "unknown" else None,
                error=message,
            )

    def provider_for_model(self, model: str) -> str:
        """Return the provider that can serve a model id."""
        codex_models = set(self.codex_settings.supported_models)
        codex_models.update(self.codex_settings.model_profiles)
        anthropic_models = set(self.anthropic_settings.supported_models)
        anthropic_models.update(self.anthropic_settings.model_profiles)
        if model in codex_models:
            return "codex"
        if model in anthropic_models:
            return "anthropic"
        raise FusionInvocationError(f"No provider can serve Fusion model {model!r}.")

    def _invoke_codex_text(
        self,
        *,
        payload: dict[str, Any],
        downstream_headers: dict[str, str],
        telemetry_id: str = "",
    ) -> FusionTextResult:
        adapted = CursorRequestAdapter(self.codex_settings).adapt(
            "chat/completions", payload, downstream_headers
        )
        auth_manager = CodexAuthManager(
            CodexAuthStore(self.codex_settings.codex_auth_path),
            refresh_skew_seconds=self.codex_settings.token_refresh_skew_seconds,
        )
        auth = auth_manager.current()
        headers = build_codex_headers(
            self.codex_settings,
            auth,
            session_id=adapted.session_id,
            thread_id=adapted.thread_id,
            downstream_headers=downstream_headers,
        )
        try:
            response = post_codex_responses(
                self.codex_settings.codex_responses_url,
                headers,
                adapted.body,
                timeout=self.fusion_settings.panel_timeout_seconds,
            )
            if response.status_code == 401:
                response.close()
                auth = auth_manager.refresh(force=True)
                headers = build_codex_headers(
                    self.codex_settings,
                    auth,
                    session_id=adapted.session_id,
                    thread_id=adapted.thread_id,
                    downstream_headers=downstream_headers,
                )
                response = post_codex_responses(
                    self.codex_settings.codex_responses_url,
                    headers,
                    adapted.body,
                    timeout=self.fusion_settings.panel_timeout_seconds,
                )
            if telemetry_id:
                telemetry.record_upstream_response(
                    telemetry_id,
                    status_code=response.status_code,
                    headers=getattr(response, "headers", None),
                )
            if response.status_code >= 400:
                raise FusionInvocationError(
                    f"Codex upstream returned HTTP {response.status_code}: "
                    f"{_response_text(response)}"
                )
            return collect_codex_text(
                _response_chunks(response), telemetry_id=telemetry_id
            )
        except (
            AuthStateError,
            UnsupportedCursorShape,
            requests.RequestException,
        ) as exc:
            raise FusionInvocationError(str(exc)) from exc
        finally:
            close = locals().get("response")
            if close is not None and callable(getattr(close, "close", None)):
                close.close()

    def _invoke_anthropic_text(
        self,
        *,
        payload: dict[str, Any],
        downstream_headers: dict[str, str],
        telemetry_id: str = "",
    ) -> FusionTextResult:
        adapted = AnthropicOpenAIRequestAdapter(self.anthropic_settings).adapt(
            "chat/completions", payload
        )
        auth_manager = AnthropicAuthManager(
            AnthropicAuthStore(self.anthropic_settings.auth_path),
            refresh_skew_seconds=self.anthropic_settings.token_refresh_skew_seconds,
        )
        auth = auth_manager.current()
        headers = build_anthropic_headers(
            self.anthropic_settings,
            auth,
            downstream_headers=downstream_headers,
            fast_mode=adapted.body.get("speed") == "fast",
        )
        try:
            response = post_anthropic_messages(
                self.anthropic_settings.messages_url,
                headers,
                adapted.body,
                timeout=self.fusion_settings.panel_timeout_seconds,
            )
            if response.status_code == 401:
                response.close()
                auth = auth_manager.refresh(force=True)
                headers = build_anthropic_headers(
                    self.anthropic_settings,
                    auth,
                    downstream_headers=downstream_headers,
                    fast_mode=adapted.body.get("speed") == "fast",
                )
                response = post_anthropic_messages(
                    self.anthropic_settings.messages_url,
                    headers,
                    adapted.body,
                    timeout=self.fusion_settings.panel_timeout_seconds,
                )
            if telemetry_id:
                telemetry.record_upstream_response(
                    telemetry_id,
                    status_code=response.status_code,
                    headers=getattr(response, "headers", None),
                )
            if response.status_code >= 400:
                raise FusionInvocationError(
                    f"Anthropic upstream returned HTTP {response.status_code}: "
                    f"{_response_text(response)}"
                )
            return collect_anthropic_text(
                _response_chunks(response), telemetry_id=telemetry_id
            )
        except (
            AnthropicAuthStateError,
            UnsupportedAnthropicShape,
            requests.RequestException,
        ) as exc:
            raise FusionInvocationError(str(exc)) from exc
        finally:
            close = locals().get("response")
            if close is not None and callable(getattr(close, "close", None)):
                close.close()


def collect_codex_text(
    chunks: Iterable[bytes], *, telemetry_id: str = ""
) -> FusionTextResult:
    """Collect assistant text and usage from a Codex Responses SSE stream."""
    decoder = SSEDecoder()
    parts: list[str] = []
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None
    for event in _events_from_chunks(decoder, chunks):
        obj = _safe_event_json(event)
        if not isinstance(obj, dict):
            continue
        event_name = event.event or str(obj.get("type") or "")
        if event_name in {
            "response.output_text.delta",
            "response.refusal.delta",
            "response.audio.transcript.delta",
        }:
            delta = obj.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
                if telemetry_id:
                    telemetry.record_stream_delta(telemetry_id, text=delta)
        elif event_name in {
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
        }:
            delta = obj.get("delta")
            if isinstance(delta, str) and telemetry_id:
                telemetry.record_stream_delta(telemetry_id, reasoning=delta)
        elif event_name == "response.completed":
            response = obj.get("response")
            if isinstance(response, dict):
                raw_usage = response.get("usage")
                usage = raw_usage if isinstance(raw_usage, dict) else usage
                stop_reason = "completed"
        elif event_name in {"response.failed", "response.incomplete"}:
            response = obj.get("response")
            if isinstance(response, dict):
                raw_usage = response.get("usage")
                usage = raw_usage if isinstance(raw_usage, dict) else usage
                stop_reason = event_name.removeprefix("response.")
    return FusionTextResult(
        text="".join(parts).strip(),
        usage=usage,
        stop_reason=stop_reason,
    )


def collect_anthropic_text(
    chunks: Iterable[bytes], *, telemetry_id: str = ""
) -> FusionTextResult:
    """Collect assistant text and usage from an Anthropic Messages SSE stream."""
    decoder = SSEDecoder()
    parts: list[str] = []
    usage: dict[str, Any] = {}
    stop_reason: str | None = None
    for event in _events_from_chunks(decoder, chunks):
        obj = _safe_event_json(event)
        if not isinstance(obj, dict):
            continue
        event_type = obj.get("type") or event.event
        if event_type == "message_start":
            message = obj.get("message")
            if isinstance(message, dict):
                _merge_numeric_usage(usage, message.get("usage"))
            continue
        if event_type == "message_delta":
            delta = obj.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
                stop_reason = delta["stop_reason"]
            _merge_numeric_usage(usage, obj.get("usage"))
            continue
        if event_type == "content_block_delta":
            delta = obj.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    if telemetry_id:
                        telemetry.record_stream_delta(telemetry_id, text=text)
            elif isinstance(delta, dict) and delta.get("type") == "thinking_delta":
                thinking = delta.get("thinking")
                if isinstance(thinking, str) and telemetry_id:
                    telemetry.record_stream_delta(telemetry_id, reasoning=thinking)
    return FusionTextResult(
        text="".join(parts).strip(),
        usage=usage or None,
        stop_reason=stop_reason,
    )


def _events_from_chunks(decoder: SSEDecoder, chunks: Iterable[bytes]) -> Iterator[Any]:
    for chunk in chunks:
        yield from decoder.feed(chunk)
    yield from decoder.flush()


def _safe_event_json(event: Any) -> Any | None:
    try:
        return event.json
    except json.JSONDecodeError:
        return None


def _response_chunks(response: Any) -> Iterator[bytes]:
    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        yield from iter_content(chunk_size=8192)
        return
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        yield content
    elif isinstance(content, str):
        yield content.encode()


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text[:1000]
    content = getattr(response, "content", b"")
    if isinstance(content, bytes):
        return content.decode(errors="replace")[:1000]
    return str(content)[:1000]


def _merge_numeric_usage(target: dict[str, Any], usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if isinstance(value, int | float):
            target[key] = int(value)
        elif isinstance(value, dict):
            target[key] = value


def _log_panel_usage(*, model: str, provider: str, result: FusionTextResult) -> None:
    usage = result.usage
    if not isinstance(usage, dict):
        console.print(
            "[bold green]FUSION USAGE:[/bold green] "
            f"model={model} provider={provider} usage=unavailable"
        )
        return
    if provider == "anthropic":
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        cache_write = int(usage.get("cache_creation_input_tokens") or 0)
        total = input_tokens + output_tokens + cache_read + cache_write
        effective_input = input_tokens + cache_read + cache_write
    else:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or input_tokens + output_tokens)
        input_details = usage.get("input_tokens_details")
        cache_read = (
            int(input_details.get("cached_tokens") or 0)
            if isinstance(input_details, dict)
            else 0
        )
        cache_write = 0
        effective_input = input_tokens
    cache_pct = (cache_read / effective_input * 100) if effective_input > 0 else 0
    console.print(
        "[bold green]FUSION USAGE:[/bold green] "
        f"model={model} provider={provider} input={input_tokens} "
        f"cache_read={cache_read} ({cache_pct:.0f}%) cache_write={cache_write} "
        f"output={output_tokens} total={total} stop={result.stop_reason or 'unknown'}"
    )
