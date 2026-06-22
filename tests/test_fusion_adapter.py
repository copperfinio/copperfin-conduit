"""Unit tests for Fusion request shaping."""

from __future__ import annotations

from flask import current_app, request

from app.anthropic.openai_request_adapter import AnthropicOpenAIRequestAdapter
from app.anthropic.settings import AnthropicModelProfile
from app.fusion.adapter import (
    FusionAdapter,
    _forward_synthesizer,
    _panel_payload,
    _synthesizer_payload,
)
from app.fusion.invoker import PanelResult
from app.fusion.settings import FusionModelProfile


class AnthropicSettingsForFusionPanel:
    """Settings stand-in for Fusion panel adapter tests."""

    supported_models = ("claude-opus-4-8",)
    model_profiles = {
        "cp-opus48-xhigh": AnthropicModelProfile(
            model="claude-opus-4-8",
            effort="xhigh",
            max_tokens=65536,
        )
    }
    cache_control = "auto"
    cache_ttl = "5m"
    thinking_display = "summarized"
    eager_tool_streaming = True


def test_panel_payload_is_text_only_and_strips_tools():
    """Private panel calls should never run Cursor tools."""
    payload = {
        "model": "cp-fusion55",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "review this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,x"},
                    },
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
        ],
        "tools": [{"type": "function", "function": {"name": "read_file"}}],
        "tool_choice": "auto",
        "stream": True,
    }

    panel_payload = _panel_payload(payload, model="cp-gpt55-xhigh", max_tokens=512)

    assert panel_payload["model"] == "cp-gpt55-xhigh"
    assert "tools" not in panel_payload
    assert "tool_choice" not in panel_payload
    assert panel_payload["max_tokens"] == 512
    assert panel_payload["max_completion_tokens"] == 512
    assert panel_payload["max_output_tokens"] == 512
    assert panel_payload["messages"][0]["role"] == "system"
    assert panel_payload["messages"][1] == {
        "role": "user",
        "content": "review this\n[image]",
    }
    assert "read_file" in panel_payload["messages"][2]["content"]


def test_fusion_opus_panel_drops_trailing_assistant_prefill():
    """Fusion's private Opus panel path must not forward assistant prefill."""
    payload = {
        "model": "cp-fusion55",
        "messages": [
            {"role": "user", "content": "review this change"},
            {"role": "assistant", "content": "I will review"},
        ],
        "stream": True,
    }

    panel_payload = _panel_payload(
        payload,
        model="cp-opus48-xhigh",
        max_tokens=512,
    )
    adapted = AnthropicOpenAIRequestAdapter(AnthropicSettingsForFusionPanel()).adapt(
        "/v1/chat/completions", panel_payload
    )

    assert adapted.upstream_model == "claude-opus-4-8"
    assert adapted.body["messages"] == [
        {
            "role": "user",
            "content": [{"type": "text", "text": "review this change"}],
        }
    ]


def test_synthesizer_payload_uses_synthesizer_model_and_preserves_tools():
    """The final Cursor-facing synthesizer turn keeps tools and panel context."""
    payload = {
        "model": "cp-fusion55",
        "messages": [{"role": "user", "content": "do the thing"}],
        "tools": [{"type": "function", "function": {"name": "write_file"}}],
        "tool_choice": "auto",
    }
    profile = FusionModelProfile(
        synthesizer_model="cp-opus48-xhigh",
        panel_models=("cp-gpt55-xhigh", "cp-opus48-xhigh"),
    )

    final_payload = _synthesizer_payload(
        payload,
        profile=profile,
        panel_results=[
            PanelResult(model="cp-gpt55-xhigh", ok=True, text="looks good"),
            PanelResult(model="cp-opus48-xhigh", ok=False, text="", error="no auth"),
        ],
    )

    assert final_payload["model"] == "cp-opus48-xhigh"
    assert final_payload["tools"] == payload["tools"]
    assert final_payload["tool_choice"] == "auto"
    assert final_payload["messages"][0]["role"] == "system"
    assert "Fusion synthesizer" in final_payload["messages"][0]["content"]
    assert "looks good" in final_payload["messages"][0]["content"]
    assert "ERROR: no auth" in final_payload["messages"][0]["content"]
    assert final_payload["messages"][1] == {"role": "user", "content": "do the thing"}


def test_forward_synthesizer_tags_fusion_telemetry(monkeypatch, app):
    """Fusion synthesizer calls remain in the Fusion run with upstream provider."""
    captured = {}

    class Invoker:
        def provider_for_model(self, model):
            assert model == "cp-gpt55-xfast"
            return "codex"

    class CodexAdapterStub:
        def forward_payload(self, payload, provider_path, downstream_headers, **kwargs):
            captured.update(
                {
                    "payload": payload,
                    "provider_path": provider_path,
                    "downstream_headers": downstream_headers,
                    "kwargs": kwargs,
                }
            )
            return "response"

    monkeypatch.setattr("app.fusion.adapter.CodexAdapter", CodexAdapterStub)
    with app.test_request_context("/v1/chat/completions", headers={"x-test": "ok"}):
        response = _forward_synthesizer(
            request,
            provider_path="chat/completions",
            payload={"model": "cp-gpt55-xfast", "messages": []},
            invoker=Invoker(),
            run_id="fusion-run-1",
        )

    assert response == "response"
    assert captured["provider_path"] == "chat/completions"
    assert captured["downstream_headers"]["X-Test"] == "ok"
    assert captured["kwargs"]["run_id"] == "fusion-run-1"
    assert captured["kwargs"]["phase"] == "synthesizer"
    assert captured["kwargs"]["label"].startswith("Synthesizer")
    assert captured["kwargs"]["label"].endswith("GPT 5.5")
    assert captured["kwargs"]["telemetry_provider"] == "fusion"
    assert captured["kwargs"]["upstream_provider"] == "codex"


def test_forward_anthropic_synthesizer_tags_fusion_telemetry(monkeypatch, app):
    """Fusion can use an Anthropic model as the final synthesizer."""
    captured = {}

    class Invoker:
        def provider_for_model(self, model):
            assert model == "cp-opus48-xhigh"
            return "anthropic"

    class AnthropicAdapterStub:
        def forward_payload(self, payload, provider_path, downstream_headers, **kwargs):
            captured.update(
                {
                    "payload": payload,
                    "provider_path": provider_path,
                    "downstream_headers": downstream_headers,
                    "kwargs": kwargs,
                }
            )
            return "response"

    monkeypatch.setattr("app.fusion.adapter.AnthropicAdapter", AnthropicAdapterStub)
    with app.test_request_context("/v1/chat/completions", headers={"x-test": "ok"}):
        response = _forward_synthesizer(
            request,
            provider_path="chat/completions",
            payload={"model": "cp-opus48-xhigh", "messages": []},
            invoker=Invoker(),
            run_id="fusion-run-1",
        )

    assert response == "response"
    assert captured["provider_path"] == "chat/completions"
    assert captured["downstream_headers"]["X-Test"] == "ok"
    assert captured["kwargs"]["run_id"] == "fusion-run-1"
    assert captured["kwargs"]["phase"] == "synthesizer"
    assert captured["kwargs"]["label"].startswith("Synthesizer")
    assert captured["kwargs"]["label"].endswith("Opus 4.8")
    assert captured["kwargs"]["telemetry_provider"] == "fusion"
    assert captured["kwargs"]["upstream_provider"] == "anthropic"


def test_panel_invocations_have_app_context(app):
    """Worker-thread panel calls can still read Flask-backed provider settings."""

    class Settings:
        panel_max_tokens = 128

    class Invoker:
        def invoke_text(
            self,
            *,
            model,
            payload,
            downstream_headers,
            phase,
            run_id,
            label,
        ):
            assert current_app.config["SERVICE_API_KEY"] == "test-service-api-key"
            assert phase == "panel"
            assert run_id == "fusion-run-1"
            assert label.startswith("Panel")
            assert label.endswith(("codex-test-model", "Opus 4.8"))
            return PanelResult(
                model=model,
                ok=True,
                text=f"{model}:{payload['max_tokens']}:{downstream_headers['x-test']}",
            )

    adapter = FusionAdapter(settings=Settings(), invoker=Invoker())
    results = adapter._run_panel(
        payload={"model": "cp-fusion55", "messages": []},
        profile=FusionModelProfile(
            synthesizer_model="codex-test-model",
            panel_models=("codex-test-model", "claude-opus-4-8"),
        ),
        downstream_headers={"x-test": "ok"},
        run_id="fusion-run-1",
    )

    assert [result.text for result in results] == [
        "codex-test-model:128:ok",
        "claude-opus-4-8:128:ok",
    ]
