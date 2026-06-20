"""Anthropic provider settings helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import current_app

from ..exceptions import ServiceConfigurationError

DEFAULT_ANTHROPIC_MODELS = (
    "claude-opus-4-8",
    "claude-sonnet-4-6",
)

_SUPPORTED_EFFORTS = {"low", "medium", "high", "xhigh", "max", "off"}
_SUPPORTED_SPEEDS = {"fast"}
_SUPPORTED_CACHE_CONTROL = {"off", "auto", "5m", "1h"}
_SUPPORTED_THINKING_DISPLAYS = {"summarized", "omitted"}


@dataclass(frozen=True)
class AnthropicModelProfile:
    """Provider-local Anthropic model alias settings."""

    model: str
    effort: str | None = None
    max_tokens: int | None = None
    speed: str | None = None


def parse_anthropic_supported_models(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated Anthropic model list."""
    if not raw:
        return DEFAULT_ANTHROPIC_MODELS
    models = tuple(item.strip() for item in raw.split(",") if item.strip())
    return models or DEFAULT_ANTHROPIC_MODELS


def parse_anthropic_model_profiles(
    raw: str | None, *, supported_models: tuple[str, ...]
) -> dict[str, AnthropicModelProfile]:
    """Parse ANTHROPIC_MODEL_PROFILES entries.

    Format: alias:target:effort[:max_tokens][:speed]
    """
    if not raw:
        return {}

    profiles: dict[str, AnthropicModelProfile] = {}
    supported = set(supported_models)
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        if len(parts) not in {3, 4, 5}:
            raise ServiceConfigurationError(
                "ANTHROPIC_MODEL_PROFILES entries must use "
                "alias:target:effort[:max_tokens][:speed] format."
            )
        alias, target, effort = parts[:3]
        if not alias or not target or not effort:
            raise ServiceConfigurationError(
                "ANTHROPIC_MODEL_PROFILES entries must include alias, target, and effort."
            )
        if target not in supported:
            raise ServiceConfigurationError(
                f"ANTHROPIC_MODEL_PROFILES target model {target!r} is not supported."
            )
        if effort not in _SUPPORTED_EFFORTS:
            raise ServiceConfigurationError(
                f"ANTHROPIC_MODEL_PROFILES effort {effort!r} is not supported."
            )

        max_tokens: int | None = None
        speed: str | None = None
        for optional in parts[3:]:
            if not optional:
                continue
            if optional.isdigit():
                max_tokens = int(optional)
                continue
            if optional in _SUPPORTED_SPEEDS:
                speed = optional
                continue
            raise ServiceConfigurationError(
                f"ANTHROPIC_MODEL_PROFILES option {optional!r} is not supported."
            )
        profiles[alias] = AnthropicModelProfile(
            model=target,
            effort=None if effort == "off" else effort,
            max_tokens=max_tokens,
            speed=speed,
        )
    return profiles


def parse_cache_control(raw: str | None) -> str:
    """Parse Anthropic prompt-cache control mode."""
    value = (raw or "auto").strip().lower()
    if value not in _SUPPORTED_CACHE_CONTROL:
        raise ServiceConfigurationError(
            "ANTHROPIC_CACHE_CONTROL must be one of: "
            + ", ".join(sorted(_SUPPORTED_CACHE_CONTROL))
        )
    return value


def parse_thinking_display(raw: str | None) -> str:
    """Parse Anthropic thinking display mode."""
    value = (raw or "summarized").strip().lower()
    if value not in _SUPPORTED_THINKING_DISPLAYS:
        raise ServiceConfigurationError(
            "ANTHROPIC_THINKING_DISPLAY must be one of: "
            + ", ".join(sorted(_SUPPORTED_THINKING_DISPLAYS))
        )
    return value


class AnthropicSettings:
    """Current Flask config projected into Anthropic provider settings."""

    @property
    def auth_path(self) -> Path:
        """Return the local Anthropic auth-state path."""
        return Path(current_app.config["ANTHROPIC_AUTH_PATH"]).expanduser()

    @property
    def base_url(self) -> str:
        """Return Anthropic base URL."""
        return str(current_app.config["ANTHROPIC_BASE_URL"]).rstrip("/")

    @property
    def messages_url(self) -> str:
        """Return Anthropic Messages upstream URL."""
        return f"{self.base_url}/v1/messages"

    @property
    def api_version(self) -> str:
        """Return Anthropic API version header."""
        return str(current_app.config["ANTHROPIC_API_VERSION"])

    @property
    def supported_models(self) -> tuple[str, ...]:
        """Return provider-local Anthropic model IDs."""
        return tuple(current_app.config["ANTHROPIC_SUPPORTED_MODELS"])

    @property
    def model_profiles(self) -> dict[str, AnthropicModelProfile]:
        """Return configured Anthropic model alias profiles."""
        return dict(current_app.config.get("ANTHROPIC_MODEL_PROFILES") or {})

    @property
    def cache_control(self) -> str:
        """Return Anthropic prompt-cache control mode."""
        return str(current_app.config["ANTHROPIC_CACHE_CONTROL"])

    @property
    def cache_ttl(self) -> str:
        """Return Anthropic prompt-cache TTL."""
        return str(current_app.config["ANTHROPIC_CACHE_TTL"])

    @property
    def thinking_display(self) -> str:
        """Return Anthropic thinking display mode."""
        return str(current_app.config["ANTHROPIC_THINKING_DISPLAY"])

    @property
    def eager_tool_streaming(self) -> bool:
        """Return whether to request fine-grained tool argument streaming."""
        return bool(current_app.config["ANTHROPIC_EAGER_TOOL_STREAMING"])

    @property
    def claude_code_version(self) -> str:
        """Return Claude Code version used in OAuth identity headers."""
        return str(current_app.config["ANTHROPIC_CLAUDE_CODE_VERSION"])

    @property
    def token_refresh_skew_seconds(self) -> int:
        """Return token refresh skew in seconds."""
        return int(current_app.config["ANTHROPIC_TOKEN_REFRESH_SKEW_SECONDS"])

    @property
    def request_timeout_seconds(self) -> float:
        """Return Anthropic upstream request timeout in seconds."""
        return float(current_app.config["ANTHROPIC_REQUEST_TIMEOUT_SECONDS"])


def anthropic_model_payload(settings: Any | None = None) -> dict[str, Any]:
    """Return a model list payload for Anthropic-compatible clients."""
    settings = settings or AnthropicSettings()
    models = [*settings.supported_models, *settings.model_profiles.keys()]
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "type": "model",
                "object": "model",
                "created": 1686935002,
                "owned_by": "anthropic",
            }
            for model in models
        ],
    }
