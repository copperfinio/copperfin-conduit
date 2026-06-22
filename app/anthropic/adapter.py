"""Flask adapter for the Anthropic provider."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests
from flask import Request, Response, jsonify, stream_with_context

from ..common.logging import console
from ..dashboard.telemetry import telemetry
from .auth_state import (
    AnthropicAuthManager,
    AnthropicAuthStateError,
    AnthropicAuthStore,
)
from .openai_request_adapter import AnthropicOpenAIRequestAdapter
from .openai_response_adapter import adapt_anthropic_sse_to_chat_sse
from .request_adapter import AnthropicRequestAdapter, UnsupportedAnthropicShape
from .response_adapter import log_anthropic_sse_usage
from .settings import AnthropicSettings
from .upstream import build_upstream_headers, post_messages


class AnthropicAdapter:
    """Forward Flask requests to Anthropic Messages."""

    def __init__(self, settings: AnthropicSettings | None = None) -> None:
        """Initialize the adapter with current Flask-backed settings."""
        self.settings = settings or AnthropicSettings()

    def ready(self) -> Response:
        """Return Anthropic readiness based on local auth state."""
        try:
            AnthropicAuthStore(self.settings.auth_path).validate_ready()
        except AnthropicAuthStateError as exc:
            return jsonify({"status": "not_ready", "error": str(exc)}), 503
        return jsonify({"status": "ready"})

    def forward(self, req: Request, provider_path: str) -> Response:
        """Forward a native Anthropic request to Anthropic."""
        payload = req.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": {"message": "Request body must be JSON"}}), 400
        return self.forward_payload(payload, provider_path, dict(req.headers))

    def forward_payload(
        self,
        payload: dict[str, Any],
        provider_path: str,
        downstream_headers: dict[str, str],
        *,
        run_id: str | None = None,
        phase: str | None = None,
        label: str | None = None,
        telemetry_provider: str = "anthropic",
        upstream_provider: str | None = None,
    ) -> Response:
        """Forward an already-decoded payload to Anthropic."""
        chat_response = _wants_chat_completion_response(provider_path)
        try:
            console.print(
                "[bold cyan]ANTHROPIC INBOUND:[/bold cyan] "
                f"path={provider_path} model={payload.get('model')!r}"
            )
            if chat_response:
                adapted = AnthropicOpenAIRequestAdapter(self.settings).adapt(
                    provider_path, payload
                )
            else:
                adapted = AnthropicRequestAdapter(self.settings).adapt(
                    provider_path, payload
                )
            auth_manager = AnthropicAuthManager(
                AnthropicAuthStore(self.settings.auth_path),
                refresh_skew_seconds=self.settings.token_refresh_skew_seconds,
            )
            auth = auth_manager.current()
        except (UnsupportedAnthropicShape, AnthropicAuthStateError) as exc:
            console.print(f"[bold red]ANTHROPIC REQUEST REJECTED:[/bold red] {exc}")
            return jsonify({"error": {"message": str(exc)}}), 400

        headers = build_upstream_headers(
            self.settings,
            auth,
            downstream_headers=downstream_headers,
            fast_mode=adapted.body.get("speed") == "fast",
        )
        telemetry_id = telemetry.record_request_start(
            provider=telemetry_provider,
            upstream_provider=upstream_provider,
            model=adapted.upstream_model or str(payload.get("model") or "unknown"),
            operation="anthropic-chat" if chat_response else "anthropic-messages",
            path=provider_path,
            payload=payload,
            phase=phase,
            run_id=run_id,
            label=label,
        )
        try:
            upstream_response = post_messages(
                self.settings.messages_url,
                headers,
                adapted.body,
                timeout=self.settings.request_timeout_seconds,
            )
            if upstream_response.status_code == 401:
                upstream_response.close()
                auth = auth_manager.refresh(force=True)
                headers = build_upstream_headers(
                    self.settings,
                    auth,
                    downstream_headers=downstream_headers,
                    fast_mode=adapted.body.get("speed") == "fast",
                )
                upstream_response = post_messages(
                    self.settings.messages_url,
                    headers,
                    adapted.body,
                    timeout=self.settings.request_timeout_seconds,
                )
        except requests.RequestException as exc:
            telemetry.record_request_end(telemetry_id, status_code=502, error=str(exc))
            return (
                jsonify(
                    {"error": {"message": f"Anthropic upstream request failed: {exc}"}}
                ),
                502,
            )
        except AnthropicAuthStateError as exc:
            telemetry.record_request_end(telemetry_id, status_code=400, error=str(exc))
            return jsonify({"error": {"message": str(exc)}}), 400

        telemetry.record_upstream_response(
            telemetry_id,
            status_code=upstream_response.status_code,
            headers=upstream_response.headers,
        )

        def stream_response():
            try:
                chunks = _response_chunks(upstream_response)
                content_type = upstream_response.headers.get("content-type", "")
                if chat_response and upstream_response.status_code == 200:
                    chunks = adapt_anthropic_sse_to_chat_sse(
                        chunks,
                        model=adapted.upstream_model,
                        telemetry_id=telemetry_id,
                    )
                elif (
                    upstream_response.status_code == 200
                    and "text/event-stream" in content_type
                ):
                    chunks = log_anthropic_sse_usage(
                        chunks,
                        model=adapted.upstream_model,
                        telemetry_id=telemetry_id,
                    )
                yield from chunks
            finally:
                telemetry.record_request_end(
                    telemetry_id, status_code=upstream_response.status_code
                )
                close = getattr(upstream_response, "close", None)
                if callable(close):
                    close()

        return Response(
            stream_with_context(stream_response()),
            status=upstream_response.status_code,
            headers={
                "content-type": upstream_response.headers.get(
                    "content-type", "text/event-stream"
                ),
                "cache-control": "no-cache",
                "x-accel-buffering": "no",
            },
        )


def _wants_chat_completion_response(path: str) -> bool:
    clean_path = path.strip("/")
    return clean_path == "chat/completions" or clean_path.endswith("/chat/completions")


def _response_chunks(response) -> Iterator[bytes]:
    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        yield from iter_content(chunk_size=8192)
        return

    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        yield content
    elif isinstance(content, str):
        yield content.encode()
