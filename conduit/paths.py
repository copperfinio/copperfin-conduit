"""Conduit filesystem paths."""

from __future__ import annotations

import os
from pathlib import Path


def conduit_home() -> Path:
    """Return Conduit's user-scoped state directory."""
    configured = os.environ.get("CONDUIT_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".conduit"


def env_path(home: Path | None = None) -> Path:
    """Return the Conduit env file path."""
    return (home or conduit_home()) / ".env"


def auth_path(home: Path | None = None) -> Path:
    """Return the Conduit Codex auth-state path."""
    return (home or conduit_home()) / "auth.json"


def anthropic_auth_path(home: Path | None = None) -> Path:
    """Return the Conduit Anthropic auth-state path."""
    return (home or conduit_home()) / "anthropic_auth.json"


def logs_dir(home: Path | None = None) -> Path:
    """Return the Conduit log directory."""
    return (home or conduit_home()) / "logs"


def run_dir(home: Path | None = None) -> Path:
    """Return the Conduit runtime metadata directory."""
    return (home or conduit_home()) / "run"


def tools_dir(home: Path | None = None) -> Path:
    """Return the Conduit managed tools directory."""
    return (home or conduit_home()) / "tools"


def ensure_conduit_home(home: Path | None = None) -> Path:
    """Create and return Conduit's user-scoped state directory."""
    root = home or conduit_home()
    root.mkdir(parents=True, exist_ok=True)
    logs_dir(root).mkdir(parents=True, exist_ok=True)
    run_dir(root).mkdir(parents=True, exist_ok=True)
    tools_dir(root).mkdir(parents=True, exist_ok=True)
    return root
