"""Anthropic upstream HTTP helpers."""

from __future__ import annotations

from typing import Any

import requests

from .auth_state import AnthropicAuthState
from .settings import AnthropicSettings

FINE_GRAINED_TOOL_STREAMING_BETA = "fine-grained-tool-streaming-2025-05-14"
FAST_MODE_BETA = "fast-mode-2026-02-01"


def build_upstream_headers(
    settings: AnthropicSettings,
    auth: AnthropicAuthState,
    *,
    downstream_headers: dict[str, str],
    fast_mode: bool = False,
) -> dict[str, str]:
    """Build headers for Anthropic Messages requests."""
    beta_features = ["claude-code-20250219", "oauth-2025-04-20"]
    if settings.eager_tool_streaming:
        beta_features.append(FINE_GRAINED_TOOL_STREAMING_BETA)
    if fast_mode:
        beta_features.append(FAST_MODE_BETA)

    headers = {
        "Authorization": f"Bearer {auth.access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "anthropic-version": settings.api_version,
        "anthropic-beta": ",".join(beta_features),
        "anthropic-dangerous-direct-browser-access": "true",
        "User-Agent": f"claude-cli/{settings.claude_code_version}",
        "x-app": "cli",
    }
    incoming_request_id = _header_get(downstream_headers, "x-request-id")
    if incoming_request_id:
        headers["x-request-id"] = incoming_request_id
    return headers


def post_messages(
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any],
    *,
    timeout: float,
) -> requests.Response:
    """Post one Anthropic Messages request."""
    return requests.post(
        url,
        headers=headers,
        json=json_body,
        stream=True,
        timeout=(60.0, timeout),
    )


def _header_get(headers: dict[str, str], key: str) -> str | None:
    for actual, value in headers.items():
        if actual.lower() == key.lower() and value:
            return value
    return None
