"""Codex ChatGPT auth-state handling."""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests

if os.name == "nt":
    import msvcrt
else:
    import fcntl

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_URL = "https://auth.openai.com/oauth/token"


class AuthStateError(RuntimeError):
    """Local Codex auth state is missing, invalid, or cannot refresh."""


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying the signature."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        raise AuthStateError("Invalid JWT in Codex auth state")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthStateError("Invalid JWT payload in Codex auth state") from exc


def _token_exp(token: str | None) -> int | None:
    if not token:
        return None
    try:
        exp = decode_jwt_payload(token).get("exp")
    except AuthStateError:
        return None
    return int(exp) if isinstance(exp, int | float) else None


def _auth_claims(id_token: str | None, access_token: str | None) -> dict[str, Any]:
    for token in (id_token, access_token):
        if not token:
            continue
        try:
            claims = decode_jwt_payload(token)
        except AuthStateError:
            continue
        nested = claims.get("https://api.openai.com/auth")
        if isinstance(nested, dict):
            return nested
        if "chatgpt_account_id" in claims:
            return claims
    return {}


@dataclass(frozen=True)
class CodexAuthState:
    """Loaded Codex auth tokens."""

    raw: dict[str, Any]
    access_token: str
    refresh_token: str
    account_id: str | None
    access_expires_at: int | None
    fedramp: bool = False

    def is_expired(self, *, skew_seconds: int) -> bool:
        """Return true when the access token should be refreshed."""
        if self.access_expires_at is None:
            return False
        return self.access_expires_at <= int(time.time()) + skew_seconds


class CodexAuthStore:
    """Read and update Codex auth state on disk."""

    def __init__(self, path: Path):
        """Initialize the store with the auth-state path."""
        self.path = path

    def load(self) -> CodexAuthState:
        """Load the local Codex auth file."""
        if not self.path.exists():
            raise AuthStateError(
                f"Codex Login State not found at {self.path}. Run `conduit auth login` first."
            )
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthStateError(
                f"Could not read Codex Login State at {self.path}"
            ) from exc

        if raw.get("auth_mode") not in {None, "chatgpt", "Chatgpt"}:
            raise AuthStateError(
                "Codex auth state must be ChatGPT auth, not API key auth."
            )
        tokens = raw.get("tokens")
        if not isinstance(tokens, dict):
            raise AuthStateError("Codex auth state is missing ChatGPT tokens.")

        id_token_raw = tokens.get("id_token")
        id_token = (
            id_token_raw.get("raw_jwt")
            if isinstance(id_token_raw, dict)
            else id_token_raw
        )
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            raise AuthStateError(
                "Codex auth state is missing access or refresh token. Run `conduit auth login` again."
            )

        claims = _auth_claims(id_token, access_token)
        account_id = tokens.get("account_id") or claims.get("chatgpt_account_id")
        return CodexAuthState(
            raw=raw,
            access_token=access_token,
            refresh_token=refresh_token,
            account_id=account_id if isinstance(account_id, str) else None,
            access_expires_at=_token_exp(access_token),
            fedramp=bool(claims.get("chatgpt_account_is_fedramp", False)),
        )

    def validate_ready(self) -> None:
        """Validate that Codex auth state is present and refreshable on disk."""
        self.load()
        try:
            with self.path.open("r", encoding="utf-8"):
                pass
        except OSError as exc:
            raise AuthStateError(
                f"Codex Login State is not readable at {self.path}"
            ) from exc
        parent = self.path.parent
        if not parent.exists():
            raise AuthStateError(f"Codex Login State directory not found at {parent}")
        if not os.access(parent, os.W_OK):
            raise AuthStateError(
                "Codex Login State directory is not writable for token refresh at "
                f"{parent}"
            )

    def save_tokens(
        self,
        *,
        current: CodexAuthState,
        id_token: str | None,
        access_token: str | None,
        refresh_token: str | None,
    ) -> CodexAuthState:
        """Persist refreshed tokens, avoiding overwriting a changed account."""
        latest = self.load()
        if latest.account_id != current.account_id:
            raise AuthStateError(
                "Codex auth account changed during refresh. Run Codex login again."
            )
        if latest.access_token != current.access_token:
            return latest

        raw = dict(latest.raw)
        tokens = dict(raw.get("tokens") or {})
        if id_token:
            tokens["id_token"] = id_token
        if access_token:
            tokens["access_token"] = access_token
        if refresh_token:
            tokens["refresh_token"] = refresh_token
        if latest.account_id and not tokens.get("account_id"):
            tokens["account_id"] = latest.account_id
        raw["tokens"] = tokens
        raw["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(raw, indent=2) + "\n")
        os.chmod(temp_path, 0o600)
        temp_path.replace(self.path)
        return self.load()

    @contextmanager
    def refresh_lock(self) -> Iterator[None]:
        """Serialize refresh-token use across local workers/processes."""
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                pass
            _lock_file(lock_file)
            try:
                yield
            finally:
                _unlock_file(lock_file)


def _lock_file(lock_file) -> None:
    """Lock a one-byte region in a cross-platform way."""
    if os.name == "nt":
        lock_file.seek(0)
        if not lock_file.read(1):
            lock_file.seek(0)
            lock_file.write("0")
            lock_file.flush()
        deadline = time.time() + 60
        while True:
            try:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.time() >= deadline:
                    raise AuthStateError(
                        "Timed out waiting for Codex auth refresh lock."
                    )
                time.sleep(0.25)
        return
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def _unlock_file(lock_file) -> None:
    """Unlock the refresh lock acquired by _lock_file."""
    if os.name == "nt":
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class CodexAuthManager:
    """Return current Codex auth state, refreshing when needed."""

    def __init__(self, store: CodexAuthStore, *, refresh_skew_seconds: int):
        """Initialize the manager with a store and refresh skew."""
        self.store = store
        self.refresh_skew_seconds = refresh_skew_seconds

    def current(self) -> CodexAuthState:
        """Load current auth state and refresh expired access tokens."""
        state = self.store.load()
        if not state.is_expired(skew_seconds=self.refresh_skew_seconds):
            return state
        return self.refresh()

    def refresh(self, *, force: bool = False) -> CodexAuthState:
        """Refresh the Codex access token."""
        with self.store.refresh_lock():
            before = self.store.load()
            if not force and not before.is_expired(
                skew_seconds=self.refresh_skew_seconds
            ):
                return before
            response = requests.post(
                REFRESH_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "client_id": CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": before.refresh_token,
                },
                timeout=30.0,
            )
            if response.status_code == 401:
                raise AuthStateError(_refresh_token_401_message(response))
            if response.status_code >= 400:
                raise AuthStateError(
                    f"Codex token refresh failed with HTTP {response.status_code}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise AuthStateError(
                    "Codex token refresh returned invalid JSON."
                ) from exc
            if not isinstance(data, dict):
                raise AuthStateError(
                    "Codex token refresh returned an unexpected response."
                )
            if not data.get("access_token"):
                raise AuthStateError(
                    "Codex token refresh did not return an access token. Run `conduit auth login` again."
                )
            return self.store.save_tokens(
                current=before,
                id_token=data.get("id_token"),
                access_token=data.get("access_token"),
                refresh_token=data.get("refresh_token"),
            )


def _refresh_token_401_message(response: requests.Response) -> str:
    """Return a clear message for known Codex refresh-token failure codes."""
    code = _refresh_error_code(response)
    if code == "refresh_token_expired":
        return "Codex refresh token has expired. Run `conduit auth login` again."
    if code == "refresh_token_reused":
        return (
            "Codex refresh token was already used. Run `conduit auth login` again and avoid "
            "sharing one auth.json across multiple active proxy or Codex processes."
        )
    if code == "refresh_token_invalidated":
        return "Codex refresh token was revoked. Run `conduit auth login` again."
    return "Codex refresh token is invalid. Run `conduit auth login` again."


def _refresh_error_code(response: requests.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return code if isinstance(code, str) else None
    if isinstance(error, str):
        return error
    code = payload.get("code")
    return code if isinstance(code, str) else None
