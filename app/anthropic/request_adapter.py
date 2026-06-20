"""Cursor Anthropic request adaptation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import AnthropicModelProfile, AnthropicSettings

_OPUS_47_PLUS_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "anthropic.claude-opus-4-7",
    "anthropic.claude-opus-4-8",
    "us.anthropic.claude-opus-4-7",
    "us.anthropic.claude-opus-4-8",
    "global.anthropic.claude-opus-4-7",
    "global.anthropic.claude-opus-4-8",
)
_UNSUPPORTED_OPUS_SAMPLING_PARAMS = {"temperature", "top_p", "top_k"}
_CLAUDE_CODE_SYSTEM = "You are Claude Code, Anthropic's official CLI for Claude."


class UnsupportedAnthropicShape(RuntimeError):
    """The downstream request is not a supported Anthropic request shape."""


@dataclass(frozen=True)
class AdaptedAnthropicRequest:
    """Anthropic upstream request body plus routing identity."""

    body: dict[str, Any]
    inbound_model: str
    upstream_model: str


class AnthropicRequestAdapter:
    """Prepare Cursor Anthropic-native requests for Anthropic upstream."""

    def __init__(self, settings: AnthropicSettings):
        """Initialize the adapter with Anthropic settings."""
        self.settings = settings

    def adapt(self, path: str, payload: dict[str, Any]) -> AdaptedAnthropicRequest:
        """Adapt an Anthropic Messages request body."""
        clean_path = path.strip("/")
        if clean_path not in {"messages", "v1/messages"}:
            raise UnsupportedAnthropicShape(
                f"Unsupported Anthropic path {path!r}; expected /v1/messages."
            )
        if not isinstance(payload, dict):
            raise UnsupportedAnthropicShape("Anthropic request body must be a JSON object.")

        body = dict(payload)
        inbound_model = self._validate_model(body)
        body["model"] = inbound_model
        self._apply_model_profile(body)
        upstream_model = str(body.get("model", ""))
        self._apply_prompt_cache(body)
        self._apply_claude_code_system(body)
        self._apply_tool_streaming(body)
        self._strip_unsupported_sampling(body)

        from ..common.logging import console

        thinking = body.get("thinking") if isinstance(body, dict) else None
        effort = None
        output_config = body.get("output_config")
        if isinstance(output_config, dict):
            effort = output_config.get("effort")
        console.print(
            "[bold cyan]ANTHROPIC REQUEST:[/bold cyan] "
            f"inbound_model={inbound_model} upstream_model={upstream_model} "
            f"effort={effort} speed={body.get('speed')} "
            f"thinking={thinking if isinstance(thinking, dict) else None}"
        )

        return AdaptedAnthropicRequest(
            body=body,
            inbound_model=inbound_model,
            upstream_model=upstream_model,
        )

    def _validate_model(self, payload: dict[str, Any]) -> str:
        model = self._resolve_model_id(payload.get("model"))
        if model is not None:
            return model
        supported_models = set(self.settings.supported_models)
        supported_models.update(self.settings.model_profiles)
        raise UnsupportedAnthropicShape(
            f"Unsupported Anthropic model {payload.get('model')!r}. Supported: "
            + ", ".join(sorted(supported_models))
        )

    def _resolve_model_id(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        model = value.strip()
        supported_models = set(self.settings.supported_models)
        supported_models.update(self.settings.model_profiles)
        if model in supported_models:
            return model

        prefix = model.rstrip(".").removesuffix("...").removesuffix("…").strip()
        if len(prefix) < 10 or prefix == model:
            return None
        matches = sorted(
            candidate for candidate in supported_models if candidate.startswith(prefix)
        )
        return matches[0] if len(matches) == 1 else None

    def _apply_model_profile(self, body: dict[str, Any]) -> None:
        profile = self.settings.model_profiles.get(body.get("model"))
        if not profile:
            return
        body["model"] = profile.model
        if profile.max_tokens is not None:
            body["max_tokens"] = profile.max_tokens
        if profile.speed is not None:
            body["speed"] = profile.speed
        if profile.effort:
            body["thinking"] = {
                "type": "adaptive",
                "display": self.settings.thinking_display,
            }
            output_config = body.get("output_config")
            if not isinstance(output_config, dict):
                output_config = {}
            else:
                output_config = dict(output_config)
            output_config["effort"] = profile.effort
            body["output_config"] = output_config

    def _apply_prompt_cache(self, body: dict[str, Any]) -> None:
        mode = self.settings.cache_control
        if mode == "off" or body.get("cache_control") is not None:
            return
        cache_control: dict[str, str] = {"type": "ephemeral"}
        ttl = self.settings.cache_ttl
        if mode == "1h" or ttl == "1h":
            cache_control["ttl"] = "1h"
        body["cache_control"] = cache_control

    def _apply_claude_code_system(self, body: dict[str, Any]) -> None:
        system = body.get("system")
        if _system_contains_claude_code(system):
            return
        identity = {"type": "text", "text": _CLAUDE_CODE_SYSTEM}
        if system is None:
            body["system"] = [identity]
        elif isinstance(system, str):
            body["system"] = [identity, {"type": "text", "text": system}]
        elif isinstance(system, list):
            body["system"] = [identity, *system]
        else:
            body["system"] = [identity]

    def _apply_tool_streaming(self, body: dict[str, Any]) -> None:
        if not self.settings.eager_tool_streaming:
            return
        tools = body.get("tools")
        if not isinstance(tools, list):
            return
        for tool in tools:
            if isinstance(tool, dict):
                tool.setdefault("eager_input_streaming", True)

    def _strip_unsupported_sampling(self, body: dict[str, Any]) -> None:
        model = str(body.get("model", ""))
        if not _is_opus_47_plus(model):
            return
        for key in _UNSUPPORTED_OPUS_SAMPLING_PARAMS:
            body.pop(key, None)


def _is_opus_47_plus(model: str) -> bool:
    return model.startswith(_OPUS_47_PLUS_PREFIXES)


def _system_contains_claude_code(system: Any) -> bool:
    if isinstance(system, str):
        return _CLAUDE_CODE_SYSTEM in system
    if isinstance(system, list):
        for item in system:
            if isinstance(item, dict) and _CLAUDE_CODE_SYSTEM in str(item.get("text", "")):
                return True
    return False
