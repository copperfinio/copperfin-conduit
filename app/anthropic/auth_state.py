"""Anthropic OAuth auth-state handling."""

from __future__ import annotations

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

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"


class AnthropicAuthStateError(RuntimeError):
    """Local Anthropic auth state is missing, invalid, or cannot refresh."""


@dataclass(frozen=True)
class AnthropicAuthState:
    """Loaded Anthropic auth tokens."""

    raw: dict[str, Any]
    access_token: str
    refresh_token: str
    access_expires_at: int | None

    def is_expired(self, *, skew_seconds: int) -> bool:
        """Return true when the access token should be refreshed."""
        if self.access_expires_at is None:
            return False
        return self.access_expires_at <= int(time.time()) + skew_seconds


class AnthropicAuthStore:
    """Read and update Anthropic auth state on disk."""

    def __init__(self, path: Path):
        """Initialize the store with the auth-state path."""
        self.path = path

    def load(self) -> AnthropicAuthState:
        """Load the local Anthropic auth file."""
        if not self.path.exists():
            raise AnthropicAuthStateError(
                f"Anthropic Login State not found at {self.path}. "
                "Run `conduit auth login --provider anthropic` first."
            )
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AnthropicAuthStateError(
                f"Could not read Anthropic Login State at {self.path}"
            ) from exc

        tokens = raw.get("tokens")
        if not isinstance(tokens, dict):
            raise AnthropicAuthStateError("Anthropic auth state is missing tokens.")
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            raise AnthropicAuthStateError(
                "Anthropic auth state is missing access or refresh token. "
                "Run `conduit auth login --provider anthropic` again."
            )
        expires_at = tokens.get("expires_at")
        if isinstance(expires_at, int | float):
            expires_seconds = int(expires_at / 1000)
        else:
            expires_seconds = None
        return AnthropicAuthState(
            raw=raw,
            access_token=str(access_token),
            refresh_token=str(refresh_token),
            access_expires_at=expires_seconds,
        )

    def validate_ready(self) -> None:
        """Validate that Anthropic auth state is present and refreshable on disk."""
        self.load()
        try:
            with self.path.open("r", encoding="utf-8"):
                pass
        except OSError as exc:
            raise AnthropicAuthStateError(
                f"Anthropic Login State is not readable at {self.path}"
            ) from exc
        parent = self.path.parent
        if not parent.exists():
            raise AnthropicAuthStateError(
                f"Anthropic Login State directory not found at {parent}"
            )
        if not os.access(parent, os.W_OK):
            raise AnthropicAuthStateError(
                "Anthropic Login State directory is not writable for token refresh at "
                f"{parent}"
            )

    def save_tokens(
        self,
        *,
        current: AnthropicAuthState,
        access_token: str | None,
        refresh_token: str | None,
        expires_in: int | float | None,
    ) -> AnthropicAuthState:
        """Persist refreshed tokens without clobbering a newer refresh."""
        latest = self.load()
        if latest.access_token != current.access_token:
            return latest

        raw = dict(latest.raw)
        tokens = dict(raw.get("tokens") or {})
        if access_token:
            tokens["access_token"] = access_token
        if refresh_token:
            tokens["refresh_token"] = refresh_token
        if isinstance(expires_in, int | float):
            tokens["expires_at"] = int(time.time() * 1000) + int(expires_in * 1000)
        raw["tokens"] = tokens
        raw["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
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


class AnthropicAuthManager:
    """Return current Anthropic auth state, refreshing when needed."""

    def __init__(self, store: AnthropicAuthStore, *, refresh_skew_seconds: int):
        """Initialize the manager with a store and refresh skew."""
        self.store = store
        self.refresh_skew_seconds = refresh_skew_seconds

    def current(self) -> AnthropicAuthState:
        """Load current auth state and refresh expired access tokens."""
        state = self.store.load()
        if not state.is_expired(skew_seconds=self.refresh_skew_seconds):
            return state
        return self.refresh()

    def refresh(self, *, force: bool = False) -> AnthropicAuthState:
        """Refresh the Anthropic access token."""
        with self.store.refresh_lock():
            before = self.store.load()
            if not force and not before.is_expired(
                skew_seconds=self.refresh_skew_seconds
            ):
                return before
            response = requests.post(
                REFRESH_URL,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": before.refresh_token,
                },
                timeout=30.0,
            )
            if response.status_code >= 400:
                raise AnthropicAuthStateError(
                    f"Anthropic token refresh failed with HTTP {response.status_code}: "
                    f"{response.text}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise AnthropicAuthStateError(
                    "Anthropic token refresh returned invalid JSON."
                ) from exc
            if not isinstance(data, dict) or not data.get("access_token"):
                raise AnthropicAuthStateError(
                    "Anthropic token refresh did not return an access token. "
                    "Run `conduit auth login --provider anthropic` again."
                )
            return self.store.save_tokens(
                current=before,
                access_token=data.get("access_token"),
                refresh_token=data.get("refresh_token"),
                expires_in=data.get("expires_in"),
            )


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
                    raise AnthropicAuthStateError(
                        "Timed out waiting for Anthropic auth refresh lock."
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
