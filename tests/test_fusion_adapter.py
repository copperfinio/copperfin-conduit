"""Unit tests for Fusion request shaping."""

from __future__ import annotations

from flask import current_app

from app.fusion.adapter import FusionAdapter
from app.fusion.adapter import _final_payload, _panel_payload
from app.fusion.invoker import PanelResult
from app.fusion.settings import FusionModelProfile


def test_panel_payload_is_text_only_and_strips_tools():
    """Private panel calls should never run Cursor tools."""
    payload = {
        "model": "cp-fusion55",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "review this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
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

    panel_payload = _panel_payload(payload, model="cp-gpt55-high", max_tokens=512)

    assert panel_payload["model"] == "cp-gpt55-high"
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


def test_final_payload_uses_primary_model_and_preserves_tools():
    """The final Cursor-facing turn keeps tools and gets advisory panel context."""
    payload = {
        "model": "cp-fusion55",
        "messages": [{"role": "user", "content": "do the thing"}],
        "tools": [{"type": "function", "function": {"name": "write_file"}}],
        "tool_choice": "auto",
    }
    profile = FusionModelProfile(
        primary_model="cp-gpt55-xfast",
        panel_models=("cp-gpt55-high", "cp-opus48-xhigh"),
    )

    final_payload = _final_payload(
        payload,
        profile=profile,
        panel_results=[
            PanelResult(model="cp-gpt55-high", ok=True, text="looks good"),
            PanelResult(model="cp-opus48-xhigh", ok=False, text="", error="no auth"),
        ],
        judge_result=None,
    )

    assert final_payload["model"] == "cp-gpt55-xfast"
    assert final_payload["tools"] == payload["tools"]
    assert final_payload["tool_choice"] == "auto"
    assert final_payload["messages"][0]["role"] == "system"
    assert "private multi-model Fusion panel" in final_payload["messages"][0]["content"]
    assert "looks good" in final_payload["messages"][0]["content"]
    assert "ERROR: no auth" in final_payload["messages"][0]["content"]
    assert final_payload["messages"][1] == {"role": "user", "content": "do the thing"}


def test_panel_invocations_have_app_context(app):
    """Worker-thread panel calls can still read Flask-backed provider settings."""

    class Settings:
        panel_max_tokens = 128

    class Invoker:
        def invoke_text(self, *, model, payload, downstream_headers):
            assert current_app.config["SERVICE_API_KEY"] == "test-service-api-key"
            return PanelResult(
                model=model,
                ok=True,
                text=f"{model}:{payload['max_tokens']}:{downstream_headers['x-test']}",
            )

    adapter = FusionAdapter(settings=Settings(), invoker=Invoker())
    results = adapter._run_panel(
        payload={"model": "cp-fusion55", "messages": []},
        profile=FusionModelProfile(
            primary_model="codex-test-model",
            panel_models=("codex-test-model", "claude-opus-4-8"),
        ),
        downstream_headers={"x-test": "ok"},
    )

    assert [result.text for result in results] == [
        "codex-test-model:128:ok",
        "claude-opus-4-8:128:ok",
    ]
