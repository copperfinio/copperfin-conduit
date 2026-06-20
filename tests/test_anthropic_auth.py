"""Tests for Conduit's direct Anthropic OAuth helpers."""

from __future__ import annotations

import json

from conduit import anthropic_auth


class FakeResponse:
    """Small requests.Response stand-in for OAuth tests."""

    def __init__(self, payload, status_code=200, reason="OK"):
        self.payload = payload
        self.status_code = status_code
        self.reason = reason
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self.payload


def test_authorization_url_matches_anthropic_oauth_shape():
    """Browser auth includes the Anthropic OAuth parameters from Pi Mono."""
    url = anthropic_auth.build_authorization_url(
        challenge="challenge", state="verifier-state"
    )

    assert url.startswith("https://claude.ai/oauth/authorize?")
    assert "client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A53692%2Fcallback" in url
    assert "code_challenge=challenge" in url
    assert "state=verifier-state" in url
    assert "user%3Asessions%3Aclaude_code" in url


def test_exchange_uses_json_anthropic_token_endpoint(monkeypatch):
    """Anthropic OAuth exchange uses the Pi Mono JSON request shape."""

    def post(url, **kwargs):
        assert url == anthropic_auth.TOKEN_URL
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["json"] == {
            "grant_type": "authorization_code",
            "client_id": anthropic_auth.CLIENT_ID,
            "code": "oauth-code",
            "state": "verifier-state",
            "redirect_uri": anthropic_auth.BROWSER_REDIRECT_URI,
            "code_verifier": "verifier-state",
        }
        return FakeResponse(
            {
                "access_token": "sk-ant-oat-access",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            }
        )

    monkeypatch.setattr(anthropic_auth.requests, "post", post)

    token = anthropic_auth.exchange_authorization_code(
        code="oauth-code",
        state="verifier-state",
        verifier="verifier-state",
        redirect_uri=anthropic_auth.BROWSER_REDIRECT_URI,
    )

    assert token.access == "sk-ant-oat-access"
    assert token.refresh == "refresh-token"


def test_refresh_uses_json_anthropic_token_endpoint(monkeypatch):
    """Anthropic refresh uses JSON, not Codex's form-encoded OAuth shape."""

    def post(url, **kwargs):
        assert url == anthropic_auth.TOKEN_URL
        assert kwargs["headers"]["Content-Type"] == "application/json"
        assert kwargs["json"] == {
            "grant_type": "refresh_token",
            "client_id": anthropic_auth.CLIENT_ID,
            "refresh_token": "refresh-token",
        }
        return FakeResponse(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }
        )

    monkeypatch.setattr(anthropic_auth.requests, "post", post)

    token = anthropic_auth.refresh_access_token("refresh-token")

    assert token.access == "new-access"
    assert token.refresh == "new-refresh"


def test_write_and_read_anthropic_auth_state(tmp_path):
    """Anthropic auth state is stored separately from Codex auth."""
    auth_path = tmp_path / "anthropic_auth.json"
    anthropic_auth.write_auth_state(
        auth_path,
        anthropic_auth.AnthropicOAuthToken(
            access="access-token",
            refresh="refresh-token",
            expires=123456,
        ),
    )

    data = json.loads(auth_path.read_text(encoding="utf-8"))
    assert data["provider"] == "anthropic"
    assert data["tokens"]["access_token"] == "access-token"
    assert anthropic_auth.read_auth_state(auth_path).refresh == "refresh-token"
