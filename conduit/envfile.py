"""Conduit environment-file handling."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from .paths import auth_path, conduit_home, ensure_conduit_home, env_path

DEFAULT_CODEX_MODELS = "gpt-5.5,gpt-5.4,gpt-5.4-mini,gpt-5.3-codex,gpt-5.3-codex-spark"
DEFAULT_MODEL_PROFILES = (
    "cp-gpt55-fast:gpt-5.5:low:priority,"
    "cp-gpt55-balanced:gpt-5.5:medium,"
    "cp-gpt55-high:gpt-5.5:high,"
    "cp-gpt55-xhigh:gpt-5.5:xhigh,"
    "cp-gpt55-xfast:gpt-5.5:xhigh:priority"
)


def default_env_text(
    *, service_key: str | None = None, home: Path | None = None
) -> str:
    """Return default Conduit env-file content."""
    root = home or conduit_home()
    key = service_key or "conduit_" + secrets.token_hex(16)
    codex_auth = auth_path(root)
    return f"""FLASK_APP=autoapp.py
FLASK_DEBUG=0
FLASK_ENV=production
LOG_CONTEXT=off
LOG_COMPLETION=on
RECORD_TRAFFIC=off
REASONING_DISPLAY_MODE=none

SERVICE_API_KEY={key}

ENABLE_AZURE=false
ENABLE_CODEX=true

AZURE_BASE_URL=https://change-me.openai.azure.com
AZURE_API_KEY=change-me
AZURE_MODEL_DEPLOYMENTS=

CODEX_AUTH_PATH={codex_auth}
CODEX_RESPONSES_URL=https://chatgpt.com/backend-api/codex/responses
CODEX_SUPPORTED_MODELS={DEFAULT_CODEX_MODELS}
CODEX_MODEL_REWRITES=
CODEX_MODEL_PROFILES={DEFAULT_MODEL_PROFILES}
CODEX_ORIGINATOR=conduit
CODEX_USER_AGENT=conduit/0.1.0
CODEX_DISCOVERY_MODE=true
CODEX_TOKEN_REFRESH_SKEW_SECONDS=300
CODEX_REQUEST_TIMEOUT_SECONDS=600
"""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple dotenv file."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_env_file(*, force: bool = False, home: Path | None = None) -> Path:
    """Create the Conduit env file if needed."""
    root = ensure_conduit_home(home)
    path = env_path(root)
    if force or not path.exists():
        path.write_text(default_env_text(home=root), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def load_env(*, home: Path | None = None) -> dict[str, str]:
    """Load Conduit's env file, creating it if missing."""
    path = ensure_env_file(home=home)
    return parse_env_file(path)


def apply_env(values: dict[str, str]) -> None:
    """Apply env-file values to the current process."""
    for key, value in values.items():
        os.environ[key] = value


def service_key(*, home: Path | None = None) -> str:
    """Return the configured service key."""
    return load_env(home=home).get("SERVICE_API_KEY", "")
