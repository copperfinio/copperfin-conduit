"""Flask blueprint and request routing for the proxy service.

This module defines the application blueprint, configures logging, and
forwards incoming HTTP requests to the configured backend implementation.
"""

from flask import Blueprint, current_app, jsonify, request

from .anthropic.adapter import AnthropicAdapter
from .anthropic.settings import anthropic_model_payload
from .auth import require_auth
from .azure.adapter import AzureAdapter
from .codex.adapter import CodexAdapter
from .codex.settings import codex_model_payload
from .common.logging import console, log_request
from .common.recording import (
    increment_last_recording,
    init_last_recording,
    record_payload,
)
from .exceptions import ConfigurationError, ServiceConfigurationError
from .fusion.adapter import FusionAdapter
from .fusion.settings import fusion_model_payload
from .models import SUPPORTED_MODELS

blueprint = Blueprint("blueprint", __name__)

ALL_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
    "TRACE",
]


# ── Health check ────────────────────────────────────────────────────────────


@blueprint.route("/health", methods=["GET"])
def health():
    """Return a simple health check payload."""
    return jsonify({"status": "ok"})


# ── Proxy catch-all ─────────────────────────────────────────────────────────


def _provider_for_path(path: str) -> tuple[str, str]:
    """Return provider name and provider-local path for an incoming path."""
    clean_path = path.strip("/")
    if clean_path == "azure" or clean_path.startswith("azure/"):
        return "azure", clean_path.removeprefix("azure").strip("/")
    if clean_path == "codex" or clean_path.startswith("codex/"):
        return "codex", clean_path.removeprefix("codex").strip("/")
    if clean_path == "anthropic" or clean_path.startswith("anthropic/"):
        return "anthropic", clean_path.removeprefix("anthropic").strip("/")
    if clean_path == "claude" or clean_path.startswith("claude/"):
        return "anthropic", clean_path.removeprefix("claude").strip("/")
    return "azure", clean_path


def _ensure_provider_enabled(provider: str) -> None:
    flag = {
        "azure": "ENABLE_AZURE",
        "codex": "ENABLE_CODEX",
        "anthropic": "ENABLE_ANTHROPIC",
    }[provider]
    if not current_app.config.get(flag, False):
        label = {
            "azure": "Azure",
            "codex": "Codex",
            "anthropic": "Anthropic",
        }[provider]
        raise ServiceConfigurationError(f"{label} provider is disabled.")


def _is_anthropic_model_request(payload: object) -> bool:
    """Return true when an OpenAI-compatible request targets a Claude model."""
    if not isinstance(payload, dict):
        return False
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return False
    if not current_app.config.get("ENABLE_ANTHROPIC", False):
        return False
    supported = set(current_app.config.get("ANTHROPIC_SUPPORTED_MODELS") or ())
    profiles = current_app.config.get("ANTHROPIC_MODEL_PROFILES") or {}
    supported.update(profiles)
    candidate = model.strip()
    if candidate in supported:
        return True
    prefix = candidate.rstrip(".").removesuffix("...").removesuffix("…").strip()
    if len(prefix) < 10 or prefix == candidate:
        return False
    return sum(1 for item in supported if item.startswith(prefix)) == 1


def _is_fusion_model_request(payload: object) -> bool:
    """Return true when an OpenAI-compatible request targets a Fusion alias."""
    if not isinstance(payload, dict):
        return False
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return False
    profiles = current_app.config.get("FUSION_MODEL_PROFILES") or {}
    return model.strip() in profiles


def _combined_codex_model_payload() -> dict:
    """Return a Codex model list plus Claude bridge and Fusion aliases."""
    payload = codex_model_payload()
    if current_app.config.get("ENABLE_ANTHROPIC", False):
        payload["data"].extend(anthropic_model_payload()["data"])
    payload["data"].extend(fusion_model_payload()["data"])
    return payload


@blueprint.route("/", defaults={"path": ""}, methods=ALL_METHODS)
@blueprint.route("/<path:path>", methods=ALL_METHODS)
@require_auth
def catch_all(path: str):
    """Forward any request path to the selected backend.

    Logs the incoming request and forwards it to the selected backend
    implementation, returning the backend's response. If forwarding fails,
    returns a 502 JSON error payload.
    """
    # Logging / recording must never crash the actual request
    try:
        if current_app.config.get("LOG_CONTEXT"):
            log_request(request)
        init_last_recording()
        increment_last_recording()
        record_payload(request.get_json(silent=True), "downstream_request")
    except (TypeError, ValueError):
        console.print_exception()
        console.print("[yellow]Logging failed but continuing with request[/yellow]")

    provider, provider_path = _provider_for_path(path)
    _ensure_provider_enabled(provider)
    if provider == "codex":
        payload = request.get_json(silent=True)
        if _is_fusion_model_request(payload):
            return FusionAdapter().forward(request, provider_path)
        if _is_anthropic_model_request(payload):
            return AnthropicAdapter().forward(request, provider_path)
        return CodexAdapter().forward(request, provider_path)
    if provider == "anthropic":
        return AnthropicAdapter().forward(request, provider_path)
    return AzureAdapter().forward(request)


# ── Model list ──────────────────────────────────────────────────────────────


@blueprint.route("/models", methods=["GET"])
@blueprint.route("/v1/models", methods=["GET"])
@blueprint.route("/azure/models", methods=["GET"])
@blueprint.route("/azure/v1/models", methods=["GET"])
@blueprint.route("/codex/models", methods=["GET"])
@blueprint.route("/codex/v1/models", methods=["GET"])
@blueprint.route("/anthropic/models", methods=["GET"])
@blueprint.route("/anthropic/v1/models", methods=["GET"])
@blueprint.route("/claude/models", methods=["GET"])
@blueprint.route("/claude/v1/models", methods=["GET"])
@require_auth
def models():
    """Return a list of available models."""
    provider, _ = _provider_for_path(request.path)
    _ensure_provider_enabled(provider)
    if provider == "codex":
        return jsonify(_combined_codex_model_payload())
    if provider == "anthropic":
        return jsonify(anthropic_model_payload())
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": 1686935002,
                    "owned_by": "openai",
                }
                for model in SUPPORTED_MODELS
            ],
        }
    )


@blueprint.route("/codex/ready", methods=["GET"])
@require_auth
def codex_ready():
    """Return Codex provider readiness."""
    _ensure_provider_enabled("codex")
    return CodexAdapter().ready()


@blueprint.route("/anthropic/ready", methods=["GET"])
@blueprint.route("/claude/ready", methods=["GET"])
@require_auth
def anthropic_ready():
    """Return Anthropic provider readiness."""
    _ensure_provider_enabled("anthropic")
    return AnthropicAdapter().ready()


@blueprint.errorhandler(ConfigurationError)
def configuration_error(e: ConfigurationError):
    """Return a 400 JSON error payload for ValueError."""
    return e.get_response_content(), 400
