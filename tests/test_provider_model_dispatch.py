"""Tests for model-based dispatch through the OpenAI-compatible Codex path."""

from __future__ import annotations

import json
from io import BytesIO

from flask import Response

from app.fusion.settings import FusionModelProfile
from conduit.anthropic_auth import AnthropicOAuthToken, write_auth_state


def test_codex_model_list_includes_claude_bridge_aliases(testapp):
    """A single Cursor OpenAI override can discover both Codex and Claude models."""
    response = testapp.get(
        "/codex/v1/models",
        headers={"Authorization": "Bearer test-service-api-key"},
        status=200,
    )

    model_ids = {item["id"] for item in response.json["data"]}
    assert "codex-test-model" in model_ids
    assert "claude-opus-4-8" in model_ids


def test_codex_model_list_includes_fusion_aliases(testapp):
    """The OpenAI-compatible model list exposes Fusion aliases for Cursor."""
    testapp.app.config["FUSION_MODEL_PROFILES"] = {
        "cp-fusion55": FusionModelProfile(
            synthesizer_model="codex-test-model",
            panel_models=("codex-test-model", "claude-opus-4-8"),
        )
    }

    response = testapp.get(
        "/codex/v1/models",
        headers={"Authorization": "Bearer test-service-api-key"},
        status=200,
    )

    model_ids = {item["id"] for item in response.json["data"]}
    assert "cp-fusion55" in model_ids


def test_codex_path_routes_fusion_alias_before_provider_dispatch(testapp, monkeypatch):
    """Fusion aliases use the Fusion adapter instead of normal provider routing."""
    captured = {}
    testapp.app.config["FUSION_MODEL_PROFILES"] = {
        "cp-fusion55": FusionModelProfile(
            synthesizer_model="codex-test-model",
            panel_models=("codex-test-model", "claude-opus-4-8"),
        )
    }

    class FakeFusionAdapter:
        def forward(self, req, provider_path):
            captured["path"] = provider_path
            captured["payload"] = req.get_json()
            return Response("fusion-ok", content_type="text/plain")

    monkeypatch.setattr("app.blueprint.FusionAdapter", FakeFusionAdapter)

    response = testapp.post(
        "/codex/chat/completions",
        headers={
            "Authorization": "Bearer test-service-api-key",
            "Content-Type": "application/json",
        },
        params=json.dumps(
            {
                "model": "cp-fusion55",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            }
        ),
        status=200,
    )

    assert response.text == "fusion-ok"
    assert captured == {
        "path": "chat/completions",
        "payload": {
            "model": "cp-fusion55",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    }


def test_codex_path_routes_claude_model_to_anthropic_bridge(
    testapp, requests_mock, tmp_path
):
    """Claude model IDs sent to /codex use Anthropic instead of Codex."""
    auth_path = tmp_path / "anthropic_auth.json"
    write_auth_state(
        auth_path,
        AnthropicOAuthToken(
            access="sk-ant-oat-test",
            refresh="refresh-token",
            expires=4102444800000,
        ),
    )
    testapp.app.config["ANTHROPIC_AUTH_PATH"] = str(auth_path)
    testapp.app.config["ANTHROPIC_MODEL_PROFILES"] = {}
    upstream = requests_mock.post(
        "https://api.anthropic.test/v1/messages",
        headers={"content-type": "text/event-stream"},
        body=BytesIO(
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"pong"}}\n\n'
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":2,"output_tokens":1}}\n\n'
        ),
    )

    response = testapp.post(
        "/codex/chat/completions",
        headers={
            "Authorization": "Bearer test-service-api-key",
            "Content-Type": "application/json",
        },
        params=json.dumps(
            {
                "model": "claude-opus-4-8",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True,
            }
        ),
        status=200,
    )

    assert upstream.called
    assert upstream.last_request.headers["Authorization"] == "Bearer sk-ant-oat-test"
    assert upstream.last_request.json()["model"] == "claude-opus-4-8"
    assert b'"content":"pong"' in response.body
