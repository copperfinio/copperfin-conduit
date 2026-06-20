"""Fusion profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import current_app

from ..exceptions import ServiceConfigurationError


@dataclass(frozen=True)
class FusionModelProfile:
    """A Cursor-facing compound model profile."""

    primary_model: str
    panel_models: tuple[str, ...]
    judge_model: str | None = None


def parse_fusion_model_profiles(
    raw: str | None, *, supported_models: set[str]
) -> dict[str, FusionModelProfile]:
    """Parse FUSION_MODEL_PROFILES entries.

    Format: alias:primary:panel1|panel2[:judge]
    """
    if not raw:
        return {}

    profiles: dict[str, FusionModelProfile] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        if len(parts) not in {3, 4}:
            raise ServiceConfigurationError(
                "FUSION_MODEL_PROFILES entries must use "
                "alias:primary:panel1|panel2[:judge] format."
            )
        alias, primary, panel_raw = parts[:3]
        judge = parts[3] if len(parts) == 4 and parts[3] else None
        panel = tuple(part.strip() for part in panel_raw.split("|") if part.strip())
        if not alias or not primary or not panel:
            raise ServiceConfigurationError(
                "FUSION_MODEL_PROFILES entries must include alias, primary, and panel models."
            )
        referenced = {primary, *panel}
        if judge:
            referenced.add(judge)
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
            primary_model=primary,
            panel_models=panel,
            judge_model=judge,
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
        """Return max tokens for each panel or judge response."""
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

