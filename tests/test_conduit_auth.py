"""Tests for Conduit's direct Codex OAuth helpers."""

from __future__ import annotations

import base64
import json
import time

import pytest

from conduit import auth


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


def access_token(account_id="account-123", exp=None):
    """Build an unsigned JWT-like token for parser tests."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = {
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    if exp is not None:
        payload["exp"] = exp
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


def test_authorization_url_matches_codex_oauth_shape():
    """Browser auth includes the OpenAI Codex OAuth parameters from Pi Mono."""
    url = auth.build_authorization_url(
        challenge="challenge", state="state-1", originator="conduit-test"
    )

    assert url.startswith("https://auth.openai.com/oauth/authorize?")
    assert "client_id=app_EMoamEEZ73f0CkXaXp7hrann" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback" in url
    assert "code_challenge=challenge" in url
    assert "codex_cli_simplified_flow=true" in url
    assert "originator=conduit-test" in url


def test_device_login_writes_codex_compatible_auth_file(monkeypatch, tmp_path):
    """Device login polls and stores auth state in the shape the proxy reads."""
    token = access_token("account-456", exp=int(time.time()) + 3600)
    auth_path = tmp_path / "auth.json"
    poll_count = 0

    def post(url, **kwargs):
        nonlocal poll_count
        if url == auth.DEVICE_USER_CODE_URL:
            assert kwargs["json"] == {"client_id": auth.CLIENT_ID}
            return FakeResponse(
                {
                    "device_auth_id": "device-auth-id",
                    "user_code": "ABCD-1234",
                    "interval": "0",
                }
            )
        if url == auth.DEVICE_TOKEN_URL:
            poll_count += 1
            assert kwargs["json"] == {
                "device_auth_id": "device-auth-id",
                "user_code": "ABCD-1234",
            }
            if poll_count == 1:
                return FakeResponse({"error": "pending"}, 403, "Forbidden")
            return FakeResponse(
                {
                    "authorization_code": "oauth-code",
                    "code_verifier": "device-code-verifier",
                }
            )
        if url == auth.TOKEN_URL:
            assert kwargs["data"]["grant_type"] == "authorization_code"
            assert kwargs["data"]["redirect_uri"] == auth.DEVICE_REDIRECT_URI
            assert kwargs["data"]["code_verifier"] == "device-code-verifier"
            return FakeResponse(
                {
                    "access_token": token,
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                }
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(auth.requests, "post", post)
    monkeypatch.setattr(auth, "sleep_with_escape", lambda seconds: None)

    credentials = auth.login_device(path=auth_path)

    assert credentials.account_id == "account-456"
    data = json.loads(auth_path.read_text(encoding="utf-8"))
    assert data["auth_mode"] == "chatgpt"
    assert data["tokens"]["access_token"] == token
    assert data["tokens"]["refresh_token"] == "refresh-token"
    assert data["tokens"]["account_id"] == "account-456"


def test_refresh_uses_form_encoded_codex_token_endpoint(monkeypatch, tmp_path):
    """Refresh follows the Pi Mono URL-encoded token request."""
    first = access_token("account-789", exp=int(time.time()) - 60)
    second = access_token("account-789", exp=int(time.time()) + 3600)
    auth_path = tmp_path / "auth.json"
    auth.write_auth_state(
        auth_path,
        auth.OAuthCredentials(
            access=first,
            refresh="refresh-token",
            expires=0,
            account_id="account-789",
        ),
    )

    def post(url, **kwargs):
        assert url == auth.TOKEN_URL
        assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
        assert kwargs["data"] == {
            "grant_type": "refresh_token",
            "client_id": auth.CLIENT_ID,
            "refresh_token": "refresh-token",
        }
        return FakeResponse(
            {
                "access_token": second,
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
            }
        )

    monkeypatch.setattr(auth.requests, "post", post)

    refreshed = auth.refresh_auth(path=auth_path)

    assert refreshed.refresh == "new-refresh-token"
    assert auth.read_auth_state(auth_path).access == second


def test_read_auth_state_rejects_missing_file(tmp_path):
    """Missing auth files produce a useful Conduit auth error."""
    with pytest.raises(auth.ConduitAuthError, match="Auth file not found"):
        auth.read_auth_state(tmp_path / "missing.json")
