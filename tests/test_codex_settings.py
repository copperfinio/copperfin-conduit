"""Unit tests for Codex settings parsing."""

import pytest

from app.codex.settings import (
    CodexModelProfile,
    codex_model_payload,
    parse_codex_model_profiles,
    parse_codex_model_rewrites,
    parse_codex_supported_models,
)
from app.exceptions import ServiceConfigurationError


def test_codex_supported_models_can_be_overridden():
    """Codex model list is comma-separated and ordered."""
    assert parse_codex_supported_models("gpt-5.5,gpt-5.4-mini") == (
        "gpt-5.5",
        "gpt-5.4-mini",
    )


def test_codex_model_rewrites_can_be_configured():
    """Codex model rewrites use source:target entries."""
    rewrites = parse_codex_model_rewrites(
        "gpt-5.4:gpt-5.5", supported_models=("gpt-5.5", "gpt-5.4")
    )

    assert rewrites == {"gpt-5.4": "gpt-5.5"}


def test_codex_model_rewrites_reject_unknown_models():
    """Model rewrite entries must reference Codex-supported models."""
    with pytest.raises(ServiceConfigurationError, match="unsupported model"):
        parse_codex_model_rewrites(
            "gpt-5.4:gpt-unknown", supported_models=("gpt-5.5", "gpt-5.4")
        )


def test_codex_model_profiles_can_be_configured():
    """Codex model profiles define aliases with effort and optional service tier."""
    profiles = parse_codex_model_profiles(
        "cp-gpt55-xfast:gpt-5.5:xhigh:priority",
        supported_models=("gpt-5.5", "gpt-5.4"),
    )

    assert profiles == {
        "cp-gpt55-xfast": CodexModelProfile(
            model="gpt-5.5", reasoning_effort="xhigh", service_tier="priority"
        )
    }


def test_codex_model_profiles_reject_unknown_targets():
    """Profile targets must reference configured upstream models."""
    with pytest.raises(ServiceConfigurationError, match="target model"):
        parse_codex_model_profiles(
            "alias:gpt-unknown:xhigh", supported_models=("gpt-5.5",)
        )


def test_codex_model_profiles_reject_unknown_efforts():
    """Profile efforts are validated to catch typos at startup."""
    with pytest.raises(ServiceConfigurationError, match="effort"):
        parse_codex_model_profiles(
            "alias:gpt-5.5:ultra", supported_models=("gpt-5.5",)
        )


def test_codex_model_payload_includes_profile_aliases():
    """Cursor's model picker can see configured aliases."""

    class Settings:
        supported_models = ("gpt-5.5",)
        model_profiles = {
            "cp-gpt55-xfast": CodexModelProfile(
                model="gpt-5.5", reasoning_effort="xhigh", service_tier="priority"
            )
        }

    payload = codex_model_payload(Settings())

    assert [model["id"] for model in payload["data"]] == [
        "gpt-5.5",
        "cp-gpt55-xfast",
    ]
