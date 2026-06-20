"""Tests for Anthropic provider routing."""

import json
from io import BytesIO

from conduit.anthropic_auth import AnthropicOAuthToken, write_auth_state


def test_anthropic_models_accepts_x_api_key(testapp):
    """Anthropic-style API key headers authenticate local model listing."""
    response = testapp.get(
        "/anthropic/v1/models",
        headers={"x-api-key": "test-service-api-key"},
        status=200,
    )

    model_ids = [item["id"] for item in response.json["data"]]
    assert model_ids == ["claude-opus-4-8", "claude-sonnet-4-6"]


def test_claude_alias_routes_to_anthropic_models(testapp):
    """The /claude prefix is an alias for Anthropic provider setup."""
    response = testapp.get(
        "/claude/v1/models",
        headers={"Authorization": "Bearer test-service-api-key"},
        status=200,
    )

    assert response.json["data"][0]["owned_by"] == "anthropic"


def test_claude_chat_completions_bridge_forwards_to_anthropic_messages(
    testapp, requests_mock, tmp_path
):
    """The /claude OpenAI-compatible path bridges Cursor traffic to Anthropic."""
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
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        ),
    )

    response = testapp.post(
        "/claude/v1/chat/completions",
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

    assert upstream.last_request.headers["Authorization"] == "Bearer sk-ant-oat-test"
    assert upstream.last_request.json()["model"] == "claude-opus-4-8"
    assert upstream.last_request.json()["messages"][0]["content"][0]["text"] == "ping"
    assert b'"content":"pong"' in response.body
    assert b'"usage"' in response.body
