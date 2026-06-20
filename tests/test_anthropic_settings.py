"""Unit tests for Anthropic settings parsing."""

import pytest

from app.anthropic.settings import (
    AnthropicModelProfile,
    anthropic_model_payload,
    parse_anthropic_model_profiles,
    parse_anthropic_supported_models,
)
from app.exceptions import ServiceConfigurationError


def test_anthropic_supported_models_can_be_overridden():
    """Anthropic model list is comma-separated and ordered."""
    assert parse_anthropic_supported_models("claude-opus-4-8,claude-sonnet-4-6") == (
        "claude-opus-4-8",
        "claude-sonnet-4-6",
    )


def test_anthropic_model_profiles_can_be_configured():
    """Anthropic profiles define aliases with effort, max tokens, and speed."""
    profiles = parse_anthropic_model_profiles(
        "cp-opus48-xfast:claude-opus-4-8:xhigh:65536:fast",
        supported_models=("claude-opus-4-8",),
    )

    assert profiles == {
        "cp-opus48-xfast": AnthropicModelProfile(
            model="claude-opus-4-8",
            effort="xhigh",
            max_tokens=65536,
            speed="fast",
        )
    }


def test_anthropic_model_profiles_reject_unknown_targets():
    """Profile targets must reference configured upstream models."""
    with pytest.raises(ServiceConfigurationError, match="target model"):
        parse_anthropic_model_profiles(
            "alias:claude-made-up:xhigh", supported_models=("claude-opus-4-8",)
        )


def test_anthropic_model_profiles_reject_unknown_efforts():
    """Profile efforts are validated to catch typos at startup."""
    with pytest.raises(ServiceConfigurationError, match="effort"):
        parse_anthropic_model_profiles(
            "alias:claude-opus-4-8:ultra", supported_models=("claude-opus-4-8",)
        )


def test_anthropic_model_payload_includes_profile_aliases():
    """Cursor's model picker can see configured Anthropic aliases."""

    class Settings:
        supported_models = ("claude-opus-4-8",)
        model_profiles = {
            "cp-opus48-ultra": AnthropicModelProfile(
                model="claude-opus-4-8", effort="xhigh"
            )
        }

    payload = anthropic_model_payload(Settings())

    assert [model["id"] for model in payload["data"]] == [
        "claude-opus-4-8",
        "cp-opus48-ultra",
    ]
