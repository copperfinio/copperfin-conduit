"""Unit tests for Fusion settings parsing."""

import pytest

from app.exceptions import ServiceConfigurationError
from app.fusion.settings import (
    FusionModelProfile,
    fusion_model_payload,
    parse_fusion_model_profiles,
)


def test_fusion_model_profiles_can_be_configured():
    """Fusion profiles define primary, panel, and optional judge models."""
    profiles = parse_fusion_model_profiles(
        "cp-fusion55:cp-gpt55-xfast:cp-gpt55-high|cp-opus48-xhigh:cp-gpt55-balanced",
        supported_models={
            "cp-gpt55-xfast",
            "cp-gpt55-high",
            "cp-opus48-xhigh",
            "cp-gpt55-balanced",
        },
    )

    assert profiles == {
        "cp-fusion55": FusionModelProfile(
            primary_model="cp-gpt55-xfast",
            panel_models=("cp-gpt55-high", "cp-opus48-xhigh"),
            judge_model="cp-gpt55-balanced",
        )
    }


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
                primary_model="cp-gpt55-xfast",
                panel_models=("cp-gpt55-high", "cp-opus48-xhigh"),
            )
        }

    payload = fusion_model_payload(Settings())

    assert [model["id"] for model in payload["data"]] == ["cp-fusion55"]
