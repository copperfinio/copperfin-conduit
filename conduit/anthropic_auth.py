"""Anthropic OAuth for Conduit.

This is ported from badlogic/pi-mono's Anthropic OAuth implementation and
rewritten for Conduit's Python CLI and auth file shape.
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .auth import (
    ConduitAuthError,
    first,
    generate_pkce,
    oauth_error_html,
    oauth_success_html,
    raise_if_escape_pressed,
    terminal_cancel_context,
)
from .paths import anthropic_auth_path, ensure_conduit_home

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
BROWSER_REDIRECT_URI = "http://localhost:53692/callback"
SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)


@dataclass(frozen=True)
class AnthropicOAuthToken:
    """Raw Anthropic OAuth token response."""

    access: str
    refresh: str
    expires: int


def login_browser(
    *, path: Path | None = None, open_browser: bool = True
) -> AnthropicOAuthToken:
    """Authenticate using Anthropic browser PKCE login and write auth state."""
    target = path or anthropic_auth_path()
    verifier, challenge = generate_pkce()
    url = build_authorization_url(challenge=challenge, state=verifier)
    server = BrowserCallbackServer(verifier)
    server.start()
    try:
        print("Open this URL to authenticate Conduit with Claude:")
        print(url)
        print()
        print("Waiting for browser callback. Press ESC to cancel.")
        if open_browser:
            webbrowser.open(url)
        code, state = wait_for_browser_code(server)
        token = exchange_authorization_code(
            code=code,
            state=state,
            verifier=verifier,
            redirect_uri=BROWSER_REDIRECT_URI,
        )
        write_auth_state(target, token)
        return token
    finally:
        server.stop()


def refresh_auth(*, path: Path | None = None) -> AnthropicOAuthToken:
    """Refresh Conduit's Anthropic auth state."""
    target = path or anthropic_auth_path()
    current = read_auth_state(target)
    token = refresh_access_token(current.refresh)
    write_auth_state(target, token)
    return token


def logout(*, path: Path | None = None) -> bool:
    """Delete Conduit's Anthropic auth state."""
    target = path or anthropic_auth_path()
    if not target.exists():
        return False
    target.unlink()
    return True


def auth_status(*, path: Path | None = None) -> dict[str, Any]:
    """Return safe Anthropic auth status for display."""
    target = path or anthropic_auth_path()
    if not target.exists():
        return {"authenticated": False, "path": str(target)}
    try:
        credentials = read_auth_state(target)
    except ConduitAuthError as exc:
        return {"authenticated": False, "path": str(target), "error": str(exc)}
    return {
        "authenticated": True,
        "path": str(target),
        "expires": credentials.expires,
        "expired": credentials.expires <= int(time.time() * 1000),
    }


def build_authorization_url(*, challenge: str, state: str) -> str:
    """Build the Anthropic OAuth authorization URL."""
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": BROWSER_REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_authorization_code(
    *, code: str, state: str, verifier: str, redirect_uri: str
) -> AnthropicOAuthToken:
    """Exchange an Anthropic authorization code for OAuth tokens."""
    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "state": state,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    return read_token_response(response, "exchange")


def refresh_access_token(refresh_token: str) -> AnthropicOAuthToken:
    """Refresh an Anthropic access token."""
    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    return read_token_response(response, "refresh")


def read_token_response(
    response: requests.Response, operation: str
) -> AnthropicOAuthToken:
    """Validate and parse an Anthropic OAuth token response."""
    if not response.ok:
        body = response.text
        raise ConduitAuthError(
            f"Anthropic token {operation} failed ({response.status_code}): "
            f"{body or response.reason}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ConduitAuthError("Anthropic token response was not JSON") from exc
    if not isinstance(data, dict):
        raise ConduitAuthError("Anthropic token response was not an object")
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise ConduitAuthError(
            f"Anthropic token {operation} response missing tokens: {data}"
        )
    if not isinstance(expires_in, int | float):
        raise ConduitAuthError(
            f"Anthropic token {operation} response missing expires_in: {data}"
        )
    return AnthropicOAuthToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000) + int(expires_in * 1000),
    )


def write_auth_state(path: Path, token: AnthropicOAuthToken) -> None:
    """Write Conduit Anthropic auth state."""
    ensure_conduit_home(path.parent)
    payload = {
        "auth_mode": "oauth",
        "tokens": {
            "access_token": token.access,
            "refresh_token": token.refresh,
            "expires_at": token.expires,
        },
        "provider": "anthropic",
        "source": "conduit",
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_auth_state(path: Path) -> AnthropicOAuthToken:
    """Read Conduit's Anthropic auth state."""
    if not path.exists():
        raise ConduitAuthError(f"Anthropic auth file not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConduitAuthError(f"Could not read Anthropic auth file at {path}") from exc
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict):
        raise ConduitAuthError("Anthropic auth file is missing tokens")
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise ConduitAuthError("Anthropic auth file is missing access or refresh token")
    expires = tokens.get("expires_at")
    if not isinstance(expires, int | float):
        expires = 0
    return AnthropicOAuthToken(
        access=access,
        refresh=refresh,
        expires=int(expires),
    )


class BrowserCallbackServer:
    """Local server that waits for Anthropic's OAuth callback."""

    def __init__(self, state: str):
        self.state = state
        self.code: str | None = None
        self.callback_state: str | None = None
        self.error: str | None = None
        self._event = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        host = os.environ.get("CONDUIT_OAUTH_CALLBACK_HOST") or os.environ.get(
            "PI_OAUTH_CALLBACK_HOST", "127.0.0.1"
        )
        callback = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self._send_html(404, oauth_error_html("Callback route not found."))
                    return
                params = parse_qs(parsed.query)
                error = first(params.get("error"))
                if error:
                    callback.error = error
                    callback._event.set()
                    self._send_html(
                        400,
                        oauth_error_html(
                            f"Anthropic authentication did not complete: {error}"
                        ),
                    )
                    return
                state = first(params.get("state"))
                if state != callback.state:
                    callback.error = "State mismatch"
                    callback._event.set()
                    self._send_html(400, oauth_error_html("State mismatch."))
                    return
                code = first(params.get("code"))
                if not code:
                    callback.error = "Missing authorization code"
                    callback._event.set()
                    self._send_html(
                        400, oauth_error_html("Missing authorization code.")
                    )
                    return
                callback.code = code
                callback.callback_state = state
                callback._event.set()
                self._send_html(
                    200,
                    oauth_success_html(
                        "Anthropic authentication completed. You can close this window."
                    ),
                )

            def _send_html(self, status: int, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        try:
            self._server = ThreadingHTTPServer((host, 53692), Handler)
        except OSError as exc:
            raise ConduitAuthError(
                f"Could not start Anthropic OAuth callback server on {host}:53692"
            ) from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    def wait(self, timeout: float) -> tuple[str, str] | None:
        self._event.wait(timeout)
        if self.error:
            raise ConduitAuthError(self.error)
        if self.code and self.callback_state:
            return self.code, self.callback_state
        return None


def wait_for_browser_code(server: BrowserCallbackServer) -> tuple[str, str]:
    """Wait for browser callback while watching for ESC."""
    with terminal_cancel_context():
        while True:
            raise_if_escape_pressed()
            result = server.wait(0.25)
            if result:
                return result
