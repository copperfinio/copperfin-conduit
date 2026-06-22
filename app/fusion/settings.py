"""Fusion profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import current_app

from ..exceptions import ServiceConfigurationError


@dataclass(frozen=True)
class FusionModelProfile:
    """A Cursor-facing compound model profile."""

    synthesizer_model: str
    panel_models: tuple[str, ...]


def parse_fusion_model_profiles(
    raw: str | None, *, supported_models: set[str]
) -> dict[str, FusionModelProfile]:
    """Parse FUSION_MODEL_PROFILES entries.

    Format: alias:synthesizer:panel1|panel2
    """
    if not raw:
        return {}

    profiles: dict[str, FusionModelProfile] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        if len(parts) != 3:
            raise ServiceConfigurationError(
                "FUSION_MODEL_PROFILES entries must use "
                "alias:synthesizer:panel1|panel2 format."
            )
        alias, synthesizer, panel_raw = parts[:3]
        panel = tuple(part.strip() for part in panel_raw.split("|") if part.strip())
        if not alias or not synthesizer or not panel:
            raise ServiceConfigurationError(
                "FUSION_MODEL_PROFILES entries must include alias, "
                "synthesizer, and panel models."
            )
        referenced = {synthesizer, *panel}
        unsupported = sorted(model for model in referenced if model not in supported_models)
        if unsupported:
            raise ServiceConfigurationError(
                "FUSION_MODEL_PROFILES references unsupported model(s): "
                + ", ".join(unsupported)
            )
        if alias in supported_models:
            raise ServiceConfigurationError(
                f"FUSION_MODEL_PROFILES alias {alias!r} conflicts with a provider model."
            )
        profiles[alias] = FusionModelProfile(
            synthesizer_model=synthesizer,
            panel_models=panel,
        )
    return profiles


class FusionSettings:
    """Current Flask config projected into Fusion settings."""

    @property
    def model_profiles(self) -> dict[str, FusionModelProfile]:
        """Return configured Fusion profiles."""
        return dict(current_app.config.get("FUSION_MODEL_PROFILES") or {})

    @property
    def panel_max_tokens(self) -> int:
        """Return max tokens for each private panel response."""
        return int(current_app.config["FUSION_PANEL_MAX_TOKENS"])

    @property
    def panel_timeout_seconds(self) -> float:
        """Return per-panel request timeout."""
        return float(current_app.config["FUSION_PANEL_TIMEOUT_SECONDS"])


def fusion_model_payload(settings: Any | None = None) -> dict[str, Any]:
    """Return OpenAI-compatible model list payload for Fusion aliases."""
    settings = settings or FusionSettings()
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": 1686935002,
                "owned_by": "copperfin",
            }
            for model in settings.model_profiles
        ],
    }
