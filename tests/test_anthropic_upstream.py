"""Tests for Anthropic upstream request headers."""

from app.anthropic.auth_state import AnthropicAuthState
from app.anthropic.upstream import build_upstream_headers


class TestSettings:
    """Small settings stand-in for upstream tests."""

    api_version = "2023-06-01"
    eager_tool_streaming = True
    claude_code_version = "2.1.75"


def test_oauth_headers_include_claude_code_identity_and_fast_beta():
    """OAuth requests use Bearer auth plus Claude Code and fast-mode headers."""
    headers = build_upstream_headers(
        TestSettings(),
        AnthropicAuthState(
            raw={},
            access_token="sk-ant-oat-token",
            refresh_token="refresh",
            access_expires_at=None,
        ),
        downstream_headers={"x-request-id": "request-123"},
        fast_mode=True,
    )

    assert headers["Authorization"] == "Bearer sk-ant-oat-token"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "claude-code-20250219" in headers["anthropic-beta"]
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    assert "fast-mode-2026-02-01" in headers["anthropic-beta"]
    assert headers["User-Agent"] == "claude-cli/2.1.75"
    assert headers["x-app"] == "cli"
    assert headers["x-request-id"] == "request-123"
