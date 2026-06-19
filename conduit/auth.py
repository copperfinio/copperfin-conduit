"""OpenAI Codex OAuth for Conduit.

The endpoint flow is ported from badlogic/pi-mono's OpenAI Codex OAuth
implementation, rewritten for Conduit's Python CLI and auth file shape.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import shutil
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .paths import auth_path, ensure_conduit_home

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_BASE_URL = "https://auth.openai.com"
AUTHORIZE_URL = f"{AUTH_BASE_URL}/oauth/authorize"
TOKEN_URL = f"{AUTH_BASE_URL}/oauth/token"
BROWSER_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEVICE_USER_CODE_URL = f"{AUTH_BASE_URL}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{AUTH_BASE_URL}/api/accounts/deviceauth/token"
DEVICE_VERIFICATION_URI = f"{AUTH_BASE_URL}/codex/device"
DEVICE_REDIRECT_URI = f"{AUTH_BASE_URL}/deviceauth/callback"
DEVICE_CODE_TIMEOUT_SECONDS = 15 * 60
SCOPE = "openid profile email offline_access"
JWT_CLAIM_PATH = "https://api.openai.com/auth"


class ConduitAuthError(RuntimeError):
    """Conduit auth failed."""


@dataclass(frozen=True)
class OAuthToken:
    """Raw OAuth token response."""

    access: str
    refresh: str
    expires: int


@dataclass(frozen=True)
class OAuthCredentials:
    """Conduit OAuth credentials."""

    access: str
    refresh: str
    expires: int
    account_id: str


@dataclass(frozen=True)
class DeviceAuthInfo:
    """OpenAI Codex device-auth response."""

    device_auth_id: str
    user_code: str
    interval_seconds: float


@dataclass(frozen=True)
class DeviceTokenSuccess:
    """Successful device-auth polling result."""

    authorization_code: str
    code_verifier: str


def login_browser(
    *,
    path: Path | None = None,
    open_browser: bool = True,
    originator: str = "conduit",
) -> OAuthCredentials:
    """Authenticate using browser PKCE login and write auth state."""
    target = path or auth_path()
    verifier, challenge = generate_pkce()
    state = secrets.token_hex(16)
    url = build_authorization_url(
        challenge=challenge, state=state, originator=originator
    )
    server = BrowserCallbackServer(state)
    server.start()
    try:
        print("Open this URL to authenticate Conduit:")
        print(url)
        print()
        print("Waiting for browser callback. Press ESC to cancel.")
        if open_browser:
            webbrowser.open(url)
        code = wait_for_browser_code(server)
        token = exchange_authorization_code(
            code=code,
            verifier=verifier,
            redirect_uri=BROWSER_REDIRECT_URI,
        )
        credentials = credentials_from_token(token)
        write_auth_state(target, credentials)
        return credentials
    finally:
        server.stop()


def login_device(
    *, path: Path | None = None, open_browser: bool = False
) -> OAuthCredentials:
    """Authenticate using OpenAI Codex device-code login and write auth state."""
    target = path or auth_path()
    device = start_device_auth()
    print("Open this URL and enter the code:")
    print(DEVICE_VERIFICATION_URI)
    print()
    print(f"Code: {device.user_code}")
    print()
    print("Waiting for authorization. Press ESC to cancel.")
    if open_browser:
        webbrowser.open(DEVICE_VERIFICATION_URI)
    token_success = poll_device_auth(device)
    token = exchange_authorization_code(
        code=token_success.authorization_code,
        verifier=token_success.code_verifier,
        redirect_uri=DEVICE_REDIRECT_URI,
    )
    credentials = credentials_from_token(token)
    write_auth_state(target, credentials)
    return credentials


def refresh_auth(*, path: Path | None = None) -> OAuthCredentials:
    """Refresh Conduit's Codex auth state."""
    target = path or auth_path()
    current = read_auth_state(target)
    token = refresh_access_token(current.refresh)
    credentials = credentials_from_token(token)
    write_auth_state(target, credentials)
    return credentials


def logout(*, path: Path | None = None) -> bool:
    """Delete Conduit's auth state."""
    target = path or auth_path()
    if not target.exists():
        return False
    target.unlink()
    return True


def import_codex_auth(*, source: Path, destination: Path | None = None) -> None:
    """Copy an existing Codex CLI auth file into Conduit's auth path."""
    dest = destination or auth_path()
    if not source.exists():
        raise ConduitAuthError(f"Source auth file not found: {source}")
    ensure_conduit_home(dest.parent)
    shutil.copyfile(source, dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass


def auth_status(*, path: Path | None = None) -> dict[str, Any]:
    """Return safe auth status for display."""
    target = path or auth_path()
    if not target.exists():
        return {"authenticated": False, "path": str(target)}
    try:
        credentials = read_auth_state(target)
    except ConduitAuthError as exc:
        return {"authenticated": False, "path": str(target), "error": str(exc)}
    return {
        "authenticated": True,
        "path": str(target),
        "account_id": credentials.account_id,
        "expires": credentials.expires,
        "expired": credentials.expires <= int(time.time() * 1000),
    }


def build_authorization_url(*, challenge: str, state: str, originator: str) -> str:
    """Build the browser OAuth authorization URL."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": BROWSER_REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": originator,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code verifier and challenge."""
    verifier = base64url_encode(secrets.token_bytes(32))
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return verifier, base64url_encode(digest)


def base64url_encode(data: bytes) -> str:
    """Encode bytes as unpadded base64url."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def exchange_authorization_code(
    *, code: str, verifier: str, redirect_uri: str
) -> OAuthToken:
    """Exchange an authorization code for OAuth tokens."""
    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    return read_token_response(response, "exchange")


def refresh_access_token(refresh_token: str) -> OAuthToken:
    """Refresh an OpenAI Codex access token."""
    response = requests.post(
        TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    return read_token_response(response, "refresh")


def read_token_response(response: requests.Response, operation: str) -> OAuthToken:
    """Validate and parse an OAuth token response."""
    if not response.ok:
        body = response.text
        raise ConduitAuthError(
            f"OpenAI Codex token {operation} failed ({response.status_code}): "
            f"{body or response.reason}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ConduitAuthError("OpenAI Codex token response was not JSON") from exc
    if not isinstance(data, dict):
        raise ConduitAuthError("OpenAI Codex token response was not an object")
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise ConduitAuthError(
            f"OpenAI Codex token {operation} response missing tokens: {data}"
        )
    if not isinstance(expires_in, int | float):
        raise ConduitAuthError(
            f"OpenAI Codex token {operation} response missing expires_in: {data}"
        )
    return OAuthToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000) + int(expires_in * 1000),
    )


def credentials_from_token(token: OAuthToken) -> OAuthCredentials:
    """Build credentials from a token response."""
    account_id = get_account_id(token.access)
    if not account_id:
        raise ConduitAuthError("Failed to extract account ID from access token")
    return OAuthCredentials(
        access=token.access,
        refresh=token.refresh,
        expires=token.expires,
        account_id=account_id,
    )


def start_device_auth() -> DeviceAuthInfo:
    """Start OpenAI Codex device-code auth."""
    response = requests.post(
        DEVICE_USER_CODE_URL,
        headers={"Content-Type": "application/json"},
        json={"client_id": CLIENT_ID},
        timeout=30,
    )
    if not response.ok:
        body = response.text
        if response.status_code == 404:
            raise ConduitAuthError(
                "OpenAI Codex device code login is not enabled for this server."
            )
        raise ConduitAuthError(
            "OpenAI Codex device code request failed with status "
            f"{response.status_code}{': ' + body if body else ''}"
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ConduitAuthError("Invalid OpenAI Codex device code response")
    device_auth_id = data.get("device_auth_id")
    user_code = data.get("user_code")
    interval = data.get("interval")
    if isinstance(interval, str):
        interval = float(interval.strip())
    if (
        not isinstance(device_auth_id, str)
        or not isinstance(user_code, str)
        or not isinstance(interval, int | float)
        or interval < 0
    ):
        raise ConduitAuthError(f"Invalid OpenAI Codex device code response: {data}")
    return DeviceAuthInfo(
        device_auth_id=device_auth_id,
        user_code=user_code,
        interval_seconds=float(interval),
    )


def poll_device_auth(device: DeviceAuthInfo) -> DeviceTokenSuccess:
    """Poll OpenAI Codex device-code auth until complete or cancelled."""
    deadline = time.time() + DEVICE_CODE_TIMEOUT_SECONDS
    interval = max(1.0, device.interval_seconds or 5.0)
    slow_downs = 0
    with terminal_cancel_context():
        while time.time() < deadline:
            raise_if_escape_pressed()
            response = requests.post(
                DEVICE_TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "device_auth_id": device.device_auth_id,
                    "user_code": device.user_code,
                },
                timeout=30,
            )
            if response.ok:
                data = response.json()
                authorization_code = data.get("authorization_code")
                code_verifier = data.get("code_verifier")
                if not isinstance(authorization_code, str) or not isinstance(
                    code_verifier, str
                ):
                    raise ConduitAuthError(
                        f"Invalid OpenAI Codex device auth token response: {data}"
                    )
                return DeviceTokenSuccess(
                    authorization_code=authorization_code,
                    code_verifier=code_verifier,
                )

            if response.status_code not in {403, 404}:
                body = response.text
                error_code = _response_error_code(body)
                if error_code == "deviceauth_authorization_pending":
                    pass
                elif error_code == "slow_down":
                    slow_downs += 1
                    interval += 5
                else:
                    raise ConduitAuthError(
                        "OpenAI Codex device auth failed with status "
                        f"{response.status_code}{': ' + body if body else ''}"
                    )

            sleep_with_escape(min(interval, max(0.0, deadline - time.time())))
    if slow_downs:
        raise ConduitAuthError(
            "Device flow timed out after slow_down responses. "
            "If this is WSL or a VM, check clock drift."
        )
    raise ConduitAuthError("Device flow timed out")


def _response_error_code(body: str) -> str | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return code if isinstance(code, str) else None
    return error if isinstance(error, str) else None


class BrowserCallbackServer:
    """Local server that waits for the browser OAuth callback."""

    def __init__(self, state: str):
        self.state = state
        self.code: str | None = None
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
                if parsed.path != "/auth/callback":
                    self._send_html(404, oauth_error_html("Callback route not found."))
                    return
                params = parse_qs(parsed.query)
                if first(params.get("state")) != callback.state:
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
                callback._event.set()
                self._send_html(
                    200,
                    oauth_success_html(
                        "OpenAI authentication completed. You can close this window."
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
            self._server = ThreadingHTTPServer((host, 1455), Handler)
        except OSError as exc:
            raise ConduitAuthError(
                f"Could not start OAuth callback server on {host}:1455"
            ) from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    def wait(self, timeout: float) -> str | None:
        self._event.wait(timeout)
        if self.error:
            raise ConduitAuthError(self.error)
        return self.code


def wait_for_browser_code(server: BrowserCallbackServer) -> str:
    """Wait for browser callback while watching for ESC."""
    with terminal_cancel_context():
        while True:
            raise_if_escape_pressed()
            code = server.wait(0.25)
            if code:
                return code


def first(values: list[str] | None) -> str | None:
    """Return first query string value."""
    return values[0] if values else None


def oauth_success_html(message: str) -> str:
    """Return a tiny success page."""
    return (
        "<!doctype html><html><body>"
        f"<h1>Conduit connected</h1><p>{html.escape(message)}</p>"
        "<script>window.close()</script>"
        "</body></html>"
    )


def oauth_error_html(message: str) -> str:
    """Return a tiny error page."""
    return (
        "<!doctype html><html><body>"
        f"<h1>Conduit auth error</h1><p>{html.escape(message)}</p>"
        "</body></html>"
    )


def write_auth_state(path: Path, credentials: OAuthCredentials) -> None:
    """Write Conduit auth state in the Codex CLI-compatible shape."""
    ensure_conduit_home(path.parent)
    payload = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": credentials.access,
            "refresh_token": credentials.refresh,
            "account_id": credentials.account_id,
            "expires_at": credentials.expires,
        },
        "provider": "openai-codex",
        "source": "conduit",
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_auth_state(path: Path) -> OAuthCredentials:
    """Read Conduit or Codex CLI auth state."""
    if not path.exists():
        raise ConduitAuthError(f"Auth file not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConduitAuthError(f"Could not read auth file at {path}") from exc
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict):
        raise ConduitAuthError("Auth file is missing tokens")
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise ConduitAuthError("Auth file is missing access or refresh token")
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        account_id = get_account_id(access)
    if not account_id:
        raise ConduitAuthError("Auth file is missing account ID")
    expires = tokens.get("expires_at")
    if not isinstance(expires, int | float):
        exp = decode_jwt_payload(access).get("exp")
        expires = int(exp * 1000) if isinstance(exp, int | float) else 0
    return OAuthCredentials(
        access=access,
        refresh=refresh,
        expires=int(expires),
        account_id=account_id,
    )


def get_account_id(access_token: str) -> str | None:
    """Extract ChatGPT account ID from an access token."""
    payload = decode_jwt_payload(access_token)
    auth = payload.get(JWT_CLAIM_PATH)
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        return account_id if isinstance(account_id, str) and account_id else None
    return None


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying it."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode("utf-8"))
    except (ValueError, OSError):
        return {}


@contextmanager
def terminal_cancel_context() -> Iterator[None]:
    """Put POSIX terminals in cbreak mode so ESC can cancel."""
    if os.name == "nt" or not sys.stdin.isatty():
        yield
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def escape_pressed() -> bool:
    """Return true when ESC has been pressed."""
    if not sys.stdin.isatty():
        return False
    if os.name == "nt":
        import msvcrt

        while msvcrt.kbhit():
            if msvcrt.getwch() == "\x1b":
                return True
        return False

    import select

    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return False
    return sys.stdin.read(1) == "\x1b"


def raise_if_escape_pressed() -> None:
    """Raise a cancellation error if ESC was pressed."""
    if escape_pressed():
        raise ConduitAuthError("Login cancelled")


def sleep_with_escape(seconds: float) -> None:
    """Sleep in small chunks so ESC can cancel."""
    end = time.time() + seconds
    while time.time() < end:
        raise_if_escape_pressed()
        time.sleep(min(0.25, max(0.0, end - time.time())))
