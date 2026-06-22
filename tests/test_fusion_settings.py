"""Unit tests for Fusion settings parsing."""

import pytest

from app.exceptions import ServiceConfigurationError
from app.fusion.settings import (
    FusionModelProfile,
    fusion_model_payload,
    parse_fusion_model_profiles,
)


def test_fusion_model_profiles_can_be_configured():
    """Fusion profiles define a synthesizer and private panel models."""
    profiles = parse_fusion_model_profiles(
        "cp-fusion55:cp-opus48-xhigh:cp-gpt55-xhigh|cp-opus48-xhigh",
        supported_models={
            "cp-gpt55-xhigh",
            "cp-opus48-xhigh",
        },
    )

    assert profiles == {
        "cp-fusion55": FusionModelProfile(
            synthesizer_model="cp-opus48-xhigh",
            panel_models=("cp-gpt55-xhigh", "cp-opus48-xhigh"),
        )
    }


def test_fusion_model_profiles_reject_legacy_four_call_shape():
    """The retired fourth call field should not be accepted silently."""
    with pytest.raises(ServiceConfigurationError, match="alias:synthesizer"):
        parse_fusion_model_profiles(
            "cp-fusion55:cp-opus48-xhigh:cp-gpt55-xhigh|cp-opus48-xhigh:cp-gpt55-balanced",
            supported_models={
                "cp-gpt55-xhigh",
                "cp-opus48-xhigh",
                "cp-gpt55-balanced",
            },
        )


def test_fusion_model_profiles_reject_unknown_models():
    """All referenced Fusion models must be provider-supported aliases."""
    with pytest.raises(ServiceConfigurationError, match="unsupported model"):
        parse_fusion_model_profiles(
            "cp-fusion55:cp-gpt55-xfast:missing",
            supported_models={"cp-gpt55-xfast"},
        )


def test_fusion_model_profiles_reject_provider_alias_conflicts():
    """Fusion aliases must not shadow normal provider model IDs."""
    with pytest.raises(ServiceConfigurationError, match="conflicts"):
        parse_fusion_model_profiles(
            "cp-gpt55-xfast:cp-gpt55-xfast:cp-gpt55-high",
            supported_models={"cp-gpt55-xfast", "cp-gpt55-high"},
        )


def test_fusion_model_payload_includes_aliases():
    """Cursor's model picker can see Fusion aliases."""

    class Settings:
        model_profiles = {
            "cp-fusion55": FusionModelProfile(
                synthesizer_model="cp-opus48-xhigh",
                panel_models=("cp-gpt55-xhigh", "cp-opus48-xhigh"),
            )
        }

    payload = fusion_model_payload(Settings())

    assert [model["id"] for model in payload["data"]] == ["cp-fusion55"]
