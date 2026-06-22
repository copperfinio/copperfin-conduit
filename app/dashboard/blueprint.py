"""Unauthenticated Flask routes for the local-only Conduit dashboard."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, render_template

from ..anthropic.auth_state import AnthropicAuthStateError, AnthropicAuthStore
from ..codex.auth_state import AuthStateError, CodexAuthStore
from .telemetry import telemetry

dashboard_blueprint = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)


@dashboard_blueprint.route("/", methods=["GET"])
def index() -> str:
    """Render the dashboard shell."""
    return render_template("dashboard.html")


@dashboard_blueprint.route("/api/snapshot", methods=["GET"])
def snapshot() -> Response:
    """Return the current in-process telemetry snapshot."""
    data = telemetry.snapshot()
    admin = build_admin_inventory(data)
    data.update(admin)
    data["ops_review"] = build_ops_review(data)
    return jsonify(data)


@dashboard_blueprint.route("/api/ops-review", methods=["GET"])
def ops_review() -> Response:
    """Return a deterministic operational review for current telemetry."""
    data = telemetry.snapshot()
    data.update(build_admin_inventory(data))
    return jsonify(build_ops_review(data))


@dashboard_blueprint.route("/api/reset", methods=["POST"])
def reset() -> Response:
    """Reset live telemetry for a fresh manual dashboard session."""
    telemetry.reset()
    return jsonify({"status": "ok"})


def build_admin_inventory(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Project runtime configuration into redacted dashboard inventory data."""
    model_catalog = build_model_catalog()
    provider_readiness = build_provider_readiness(model_catalog)
    route_catalog = build_route_catalog(snapshot, model_catalog, provider_readiness)
    diagnostics = build_diagnostics(model_catalog, provider_readiness, route_catalog)
    return {
        "model_catalog": model_catalog,
        "provider_readiness": provider_readiness,
        "route_catalog": route_catalog,
        "diagnostics": diagnostics,
    }


def build_model_catalog() -> dict[str, Any]:
    """Return configured model aliases and provider-local model IDs."""
    rows: list[dict[str, Any]] = []
    enabled = {
        "azure": bool(current_app.config.get("ENABLE_AZURE", False)),
        "codex": bool(current_app.config.get("ENABLE_CODEX", False)),
        "anthropic": bool(current_app.config.get("ENABLE_ANTHROPIC", False)),
        "fusion": bool(current_app.config.get("FUSION_MODEL_PROFILES") or {}),
    }

    for model, deployment in sorted((current_app.config.get("AZURE_MODEL_DEPLOYMENTS") or {}).items()):
        rows.append(
            _model_row(
                model_id=str(model),
                provider="azure",
                source="native",
                upstream_model=str(deployment),
                compatibility="OpenAI responses / chat",
                endpoint="/v1/chat/completions",
                enabled=enabled["azure"],
                details={"deployment": deployment},
            )
        )

    for model in current_app.config.get("CODEX_SUPPORTED_MODELS") or ():
        rows.append(
            _model_row(
                model_id=str(model),
                provider="codex",
                source="native",
                upstream_model=str(model),
                compatibility="OpenAI chat",
                endpoint="/codex/v1/chat/completions",
                enabled=enabled["codex"],
            )
        )

    for alias, profile in sorted((current_app.config.get("CODEX_MODEL_PROFILES") or {}).items()):
        payload = _profile_payload(profile)
        rows.append(
            _model_row(
                model_id=str(alias),
                provider="codex",
                source="alias",
                upstream_model=str(payload.get("model") or ""),
                compatibility="OpenAI chat",
                endpoint="/codex/v1/chat/completions",
                enabled=enabled["codex"],
                details={
                    "reasoning_effort": payload.get("reasoning_effort"),
                    "service_tier": payload.get("service_tier"),
                },
            )
        )

    for model in current_app.config.get("ANTHROPIC_SUPPORTED_MODELS") or ():
        rows.append(
            _model_row(
                model_id=str(model),
                provider="anthropic",
                source="native",
                upstream_model=str(model),
                compatibility="Anthropic messages / OpenAI bridge",
                endpoint="/anthropic/v1/messages",
                enabled=enabled["anthropic"],
            )
        )

    for alias, profile in sorted(
        (current_app.config.get("ANTHROPIC_MODEL_PROFILES") or {}).items()
    ):
        payload = _profile_payload(profile)
        rows.append(
            _model_row(
                model_id=str(alias),
                provider="anthropic",
                source="alias",
                upstream_model=str(payload.get("model") or ""),
                compatibility="Anthropic messages / OpenAI bridge",
                endpoint="/codex/v1/chat/completions",
                enabled=enabled["anthropic"],
                details={
                    "effort": payload.get("effort"),
                    "max_tokens": payload.get("max_tokens"),
                    "speed": payload.get("speed"),
                },
            )
        )

    for alias, profile in sorted((current_app.config.get("FUSION_MODEL_PROFILES") or {}).items()):
        payload = _profile_payload(profile)
        rows.append(
            _model_row(
                model_id=str(alias),
                provider="fusion",
                source="alias",
                upstream_model=str(payload.get("synthesizer_model") or ""),
                compatibility="OpenAI chat compound model",
                endpoint="/codex/v1/chat/completions",
                enabled=enabled["fusion"],
                details={
                    "synthesizer_model": payload.get("synthesizer_model"),
                    "panel_models": list(payload.get("panel_models") or ()),
                    "panel_count": len(payload.get("panel_models") or ()),
                },
            )
        )

    providers: dict[str, dict[str, Any]] = {}
    for row in rows:
        provider = row["provider"]
        item = providers.setdefault(
            provider,
            {"provider": provider, "total": 0, "aliases": 0, "native": 0, "enabled": enabled.get(provider, False)},
        )
        item["total"] += 1
        item["aliases"] += 1 if row["source"] == "alias" else 0
        item["native"] += 1 if row["source"] == "native" else 0

    return {
        "generated_at": time.time(),
        "summary": {
            "total_models": len(rows),
            "aliases": sum(1 for row in rows if row["source"] == "alias"),
            "native": sum(1 for row in rows if row["source"] == "native"),
            "enabled_providers": sum(1 for value in enabled.values() if value),
        },
        "providers": list(providers.values()),
        "rows": rows,
    }


def build_provider_readiness(model_catalog: dict[str, Any]) -> dict[str, Any]:
    """Return provider enablement and auth-state readiness without leaking tokens."""
    rows = [
        _azure_readiness(),
        _codex_readiness(),
        _anthropic_readiness(),
        _fusion_readiness(model_catalog),
    ]
    return {
        "generated_at": time.time(),
        "summary": {
            "providers": len(rows),
            "ready": sum(1 for row in rows if row["state"] == "ready"),
            "disabled": sum(1 for row in rows if row["state"] == "disabled"),
            "attention": sum(1 for row in rows if row["state"] in {"missing", "expired", "error"}),
        },
        "rows": rows,
    }


def build_route_catalog(
    snapshot: dict[str, Any],
    model_catalog: dict[str, Any],
    provider_readiness: dict[str, Any],
) -> dict[str, Any]:
    """Return configured endpoint behavior plus recent routing decisions."""
    readiness = {row["provider"]: row for row in provider_readiness.get("rows") or []}
    models = model_catalog.get("rows") or []
    fusion_aliases = [row["id"] for row in models if row["provider"] == "fusion"]
    anthropic_aliases = [
        row["id"]
        for row in models
        if row["provider"] == "anthropic" and row["source"] == "alias"
    ]

    routes = [
        _route_row(
            "codex-openai-chat",
            "/codex/v1/chat/completions",
            "OpenAI chat",
            "Codex",
            "Default for Codex and GPT profile aliases.",
            readiness.get("codex"),
            model_count=sum(1 for row in models if row["provider"] == "codex"),
        ),
        _route_row(
            "anthropic-openai-bridge",
            "/codex/v1/chat/completions",
            "OpenAI chat",
            "Anthropic bridge",
            "Claude aliases sent through the OpenAI-compatible route are dispatched to Anthropic.",
            readiness.get("anthropic"),
            model_count=len(anthropic_aliases),
            aliases=anthropic_aliases,
        ),
        _route_row(
            "anthropic-native",
            "/anthropic/v1/messages",
            "Anthropic messages",
            "Anthropic",
            "Native Claude-compatible messages endpoint.",
            readiness.get("anthropic"),
            model_count=sum(1 for row in models if row["provider"] == "anthropic"),
        ),
        _route_row(
            "claude-native-alias",
            "/claude/v1/messages",
            "Anthropic messages",
            "Anthropic",
            "Convenience alias for native Claude-compatible messages.",
            readiness.get("anthropic"),
            model_count=sum(1 for row in models if row["provider"] == "anthropic"),
        ),
        _route_row(
            "fusion-openai-chat",
            "/codex/v1/chat/completions",
            "OpenAI chat",
            "Fusion",
            "Fusion aliases fan out to private panel calls, then a synthesizer call.",
            readiness.get("fusion"),
            model_count=len(fusion_aliases),
            aliases=fusion_aliases,
        ),
        _route_row(
            "azure-default",
            "/v1/chat/completions",
            "OpenAI chat",
            "Azure",
            "Unprefixed requests fall through to Azure when enabled.",
            readiness.get("azure"),
            model_count=len(current_app.config.get("AZURE_MODEL_DEPLOYMENTS") or {}),
        ),
    ]

    decisions = _recent_route_decisions(snapshot)
    return {
        "generated_at": time.time(),
        "summary": {
            "routes": len(routes),
            "enabled": sum(1 for row in routes if row["enabled"]),
            "recent_decisions": len(decisions),
            "recent_errors": sum(1 for row in decisions if row["state"] == "error"),
        },
        "routes": routes,
        "recent_decisions": decisions,
    }


def build_diagnostics(
    model_catalog: dict[str, Any],
    provider_readiness: dict[str, Any],
    route_catalog: dict[str, Any],
) -> dict[str, Any]:
    """Return redacted effective settings for local diagnostics."""
    keys = [
        "FLASK_ENV",
        "DEBUG",
        "RECORD_TRAFFIC",
        "LOG_CONTEXT",
        "LOG_COMPLETION",
        "REASONING_DISPLAY_MODE",
        "DASHBOARD_PORT",
        "ENABLE_AZURE",
        "ENABLE_CODEX",
        "ENABLE_ANTHROPIC",
        "CODEX_AUTH_PATH",
        "CODEX_DISCOVERY_MODE",
        "CODEX_REQUEST_TIMEOUT_SECONDS",
        "ANTHROPIC_AUTH_PATH",
        "ANTHROPIC_CACHE_CONTROL",
        "ANTHROPIC_CACHE_TTL",
        "ANTHROPIC_THINKING_DISPLAY",
        "ANTHROPIC_EAGER_TOOL_STREAMING",
        "ANTHROPIC_TOKEN_REFRESH_SKEW_SECONDS",
        "ANTHROPIC_REQUEST_TIMEOUT_SECONDS",
        "CODEX_TOKEN_REFRESH_SKEW_SECONDS",
        "FUSION_PANEL_MAX_TOKENS",
        "FUSION_PANEL_TIMEOUT_SECONDS",
        "AZURE_BASE_URL",
        "AZURE_RESPONSES_API_URL",
        "SERVICE_API_KEY",
        "AZURE_API_KEY",
    ]
    settings = [
        {
            "key": key,
            "value": _redacted_config_value(key, current_app.config.get(key)),
            "redacted": _is_sensitive_key(key),
        }
        for key in keys
        if key in current_app.config
    ]
    return {
        "generated_at": time.time(),
        "summary": {
            "settings": len(settings),
            "models": (model_catalog.get("summary") or {}).get("total_models", 0),
            "providers_ready": (provider_readiness.get("summary") or {}).get("ready", 0),
            "routes_enabled": (route_catalog.get("summary") or {}).get("enabled", 0),
        },
        "settings": settings,
        "notes": [
            "Dashboard data is in-process for the current proxy service instance.",
            "Credential-like values are redacted before they reach the browser.",
            "Auth readiness checks validate local files only; they do not refresh tokens.",
        ],
    }


def _model_row(
    *,
    model_id: str,
    provider: str,
    source: str,
    upstream_model: str,
    compatibility: str,
    endpoint: str,
    enabled: bool,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "provider": provider,
        "source": source,
        "upstream_model": upstream_model,
        "compatibility": compatibility,
        "endpoint": endpoint,
        "enabled": enabled,
        "state": "available" if enabled else "disabled",
        "details": _clean_details(details or {}),
    }


def _route_row(
    route_id: str,
    path: str,
    protocol: str,
    target: str,
    behavior: str,
    readiness: dict[str, Any] | None,
    *,
    model_count: int,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    state = (readiness or {}).get("state") or "unknown"
    return {
        "id": route_id,
        "path": path,
        "protocol": protocol,
        "target": target,
        "behavior": behavior,
        "enabled": state in {"ready", "warning"},
        "state": state,
        "model_count": model_count,
        "aliases": aliases or [],
    }


def _azure_readiness() -> dict[str, Any]:
    enabled = bool(current_app.config.get("ENABLE_AZURE", False))
    base_url = str(current_app.config.get("AZURE_BASE_URL") or "")
    api_key = str(current_app.config.get("AZURE_API_KEY") or "")
    configured = bool(
        base_url
        and base_url != "change_me"
        and api_key
        and api_key != "change_me"
    )
    return {
        "provider": "azure",
        "label": "Azure",
        "enabled": enabled,
        "state": "ready" if enabled and configured else "disabled" if not enabled else "missing",
        "auth": "api key configured" if configured else "api key missing",
        "path": None,
        "expires_at": None,
        "account": None,
        "detail": "Azure fallback route" if enabled else "Provider disabled",
    }


def _codex_readiness() -> dict[str, Any]:
    enabled = bool(current_app.config.get("ENABLE_CODEX", False))
    if not enabled:
        return _disabled_readiness("codex", "Codex", current_app.config.get("CODEX_AUTH_PATH"))

    path = Path(current_app.config["CODEX_AUTH_PATH"]).expanduser()
    store = CodexAuthStore(path)
    try:
        state = store.load()
        auth_state = "expired" if state.is_expired(
            skew_seconds=int(current_app.config.get("CODEX_TOKEN_REFRESH_SKEW_SECONDS", 300))
        ) else "ready"
        detail = "auth file loaded"
        account = _mask_identifier(state.account_id)
        expires_at = state.access_expires_at
    except AuthStateError as exc:
        auth_state = "missing" if not path.exists() else "error"
        detail = str(exc)
        account = None
        expires_at = None
    return {
        "provider": "codex",
        "label": "Codex",
        "enabled": enabled,
        "state": auth_state,
        "auth": "ChatGPT OAuth",
        "path": _display_path(path),
        "expires_at": expires_at,
        "account": account,
        "detail": _safe_detail(detail),
    }


def _anthropic_readiness() -> dict[str, Any]:
    enabled = bool(current_app.config.get("ENABLE_ANTHROPIC", False))
    if not enabled:
        return _disabled_readiness(
            "anthropic",
            "Anthropic",
            current_app.config.get("ANTHROPIC_AUTH_PATH"),
        )

    path = Path(current_app.config["ANTHROPIC_AUTH_PATH"]).expanduser()
    store = AnthropicAuthStore(path)
    try:
        state = store.load()
        auth_state = "expired" if state.is_expired(
            skew_seconds=int(current_app.config.get("ANTHROPIC_TOKEN_REFRESH_SKEW_SECONDS", 300))
        ) else "ready"
        detail = "auth file loaded"
        expires_at = state.access_expires_at
    except AnthropicAuthStateError as exc:
        auth_state = "missing" if not path.exists() else "error"
        detail = str(exc)
        expires_at = None
    return {
        "provider": "anthropic",
        "label": "Anthropic",
        "enabled": enabled,
        "state": auth_state,
        "auth": "Claude OAuth",
        "path": _display_path(path),
        "expires_at": expires_at,
        "account": None,
        "detail": _safe_detail(detail),
    }


def _fusion_readiness(model_catalog: dict[str, Any]) -> dict[str, Any]:
    profiles = current_app.config.get("FUSION_MODEL_PROFILES") or {}
    model_rows = model_catalog.get("rows") or []
    aliases = [row["id"] for row in model_rows if row["provider"] == "fusion"]
    enabled = bool(profiles)
    return {
        "provider": "fusion",
        "label": "Fusion",
        "enabled": enabled,
        "state": "ready" if enabled else "disabled",
        "auth": "delegates to panel providers",
        "path": None,
        "expires_at": None,
        "account": None,
        "detail": (
            f"{len(aliases)} Fusion alias{'es' if len(aliases) != 1 else ''} configured"
            if aliases
            else "No Fusion aliases configured"
        ),
    }


def _disabled_readiness(provider: str, label: str, path: Any) -> dict[str, Any]:
    return {
        "provider": provider,
        "label": label,
        "enabled": False,
        "state": "disabled",
        "auth": "disabled",
        "path": _display_path(Path(path).expanduser()) if path else None,
        "expires_at": None,
        "account": None,
        "detail": "Provider disabled",
    }


def _recent_route_decisions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records = [*(snapshot.get("active_requests") or []), *(snapshot.get("recent_requests") or [])]
    rows: list[dict[str, Any]] = []
    for record in records[:60]:
        status = _safe_int(record.get("final_status") or record.get("upstream_status"))
        ok = not _request_is_error(record)
        rows.append(
            {
                "request_id": record.get("id"),
                "started_at": record.get("started_at"),
                "ended_at": record.get("ended_at"),
                "provider": record.get("provider") or "unknown",
                "upstream_provider": record.get("upstream_provider") or record.get("provider") or "unknown",
                "phase": record.get("phase") or "",
                "model": record.get("display_label") or record.get("label") or record.get("model") or "unknown model",
                "operation": record.get("operation") or "",
                "path": record.get("path") or "",
                "status_code": status or None,
                "state": "ok" if ok else "error",
                "error_type": record.get("error_type") or "",
                "retryable": bool(record.get("retryable")),
                "tier": record.get("tier") or "",
                "plan": record.get("plan") or "",
            }
        )
    return rows


def _profile_payload(profile: Any) -> dict[str, Any]:
    if is_dataclass(profile):
        return asdict(profile)
    if isinstance(profile, dict):
        return dict(profile)
    return {
        key: getattr(profile, key)
        for key in dir(profile)
        if not key.startswith("_") and not callable(getattr(profile, key))
    }


def _clean_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in details.items()
        if not _is_empty_detail(value)
    }


def _is_empty_detail(value: Any) -> bool:
    return value is None or value == "" or value == () or value == []


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    sensitive_markers = (
        "api_key",
        "service_api_key",
        "access_token",
        "refresh_token",
        "id_token",
        "secret",
        "password",
        "bearer",
    )
    return any(marker in lowered for marker in sensitive_markers)


def _redacted_config_value(key: str, value: Any) -> str:
    if _is_sensitive_key(key):
        return "[redacted]" if value else "[not set]"
    if isinstance(value, Path):
        return _display_path(value.expanduser())
    if isinstance(value, dict):
        return f"{len(value)} configured"
    if isinstance(value, (tuple, list, set)):
        return f"{len(value)} configured"
    if value is None:
        return ""
    return str(value)


def _display_path(path: Path) -> str:
    try:
        home = Path.home().resolve()
        resolved = path.resolve()
        relative = resolved.relative_to(home)
        return os.path.join("~", str(relative))
    except (OSError, ValueError):
        return str(path)


def _mask_identifier(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return f"{value[:2]}..."
    return f"{value[:4]}...{value[-4:]}"


def _safe_detail(value: str) -> str:
    return str(value).replace(str(Path.home()), "~")[:260]


def build_ops_review(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build a small, actionable health review from live dashboard telemetry."""
    totals = snapshot.get("totals") or {}
    providers = snapshot.get("providers") or {}
    fusion_runs = snapshot.get("fusion_runs") or []
    recent_requests = snapshot.get("recent_requests") or []
    active_requests = snapshot.get("active_requests") or []

    request_count = _safe_int(totals.get("requests"))
    active_count = _safe_int(totals.get("active"))
    error_count = _safe_int(totals.get("errors"))
    error_rate = (error_count / request_count) if request_count else 0.0
    score = 100
    findings: list[dict[str, str]] = []
    provider_posture: list[dict[str, str]] = []

    if request_count == 0:
        score -= 12
        findings.append(
            _finding(
                "info",
                "Telemetry",
                "No traffic observed",
                "The proxy has not recorded completed model calls in this process yet.",
                "Requests: 0",
                "Send a small request through GPT, Claude, or Fusion to validate routing.",
            )
        )

    if error_count:
        score -= min(42, 14 + round(error_rate * 100))
        findings.append(
            _finding(
                "error" if error_rate >= 0.1 else "warning",
                "Routing",
                "Upstream errors present",
                f"{error_count} of {request_count} tracked calls ended in an error.",
                f"Error rate: {_format_pct(error_rate)}",
                "Open Recent calls and inspect the provider/model attached to the failing rows.",
            )
        )

    if active_count:
        slow_active = [
            request
            for request in active_requests
            if _safe_int(request.get("duration_ms")) >= 30_000
        ]
        score -= min(20, active_count * 3)
        findings.append(
            _finding(
                "warning" if slow_active else "info",
                "Streaming",
                "Requests in flight",
                f"{active_count} request{'s are' if active_count != 1 else ' is'} currently active.",
                f"Slow active: {len(slow_active)}",
                "If this count sticks, check streaming completion and client disconnect handling.",
            )
        )

    route_rows = _route_guardrail_rows([*recent_requests, *active_requests])
    failing_routes = [row for row in route_rows if row["errors"] > 0]
    stream_risk_routes = [row for row in route_rows if row["brick_risk"]]
    cold_hot_routes = [
        row
        for row in route_rows
        if row["calls"] >= 3 and row["cache_ratio"] < 0.05 and row["tokens"] >= 1_000
    ]

    if failing_routes:
        worst = failing_routes[0]
        score -= min(20, 6 + len(failing_routes) * 3)
        findings.append(
            _finding(
                "error",
                "Route guardrail",
                "Routes are breaching error SLO",
                f"{len(failing_routes)} provider/model route{'s' if len(failing_routes) != 1 else ''} recorded errors.",
                f"{worst['label']}: {worst['errors']}/{worst['calls']} failed",
                "Open the Route SLO board and inspect auth, model id, and unsupported parameters for the worst lane.",
            )
        )

    if stream_risk_routes:
        worst = stream_risk_routes[0]
        score -= min(12, len(stream_risk_routes) * 4)
        findings.append(
            _finding(
                "warning",
                "Streaming",
                "Possible buffered stream lanes",
                f"{len(stream_risk_routes)} route{'s' if len(stream_risk_routes) != 1 else ''} produced a lot of text with too few chunks.",
                f"{worst['label']}: {worst['chars']} chars / {worst['chunks']} chunks",
                "Inspect stream adapters for coalesced deltas or client-side buffering.",
            )
        )

    if cold_hot_routes:
        worst = cold_hot_routes[0]
        score -= min(8, len(cold_hot_routes) * 2)
        findings.append(
            _finding(
                "info",
                "Cache",
                "Hot routes are missing cache",
                f"{len(cold_hot_routes)} high-token route{'s are' if len(cold_hot_routes) != 1 else ' is'} showing cold cache behavior.",
                f"{worst['label']}: {_format_pct(worst['cache_ratio'])} cache across {worst['calls']} calls",
                "Check whether repeated system prompts are eligible for provider prompt caching.",
            )
        )

    for provider_key, provider in providers.items():
        requests = _safe_int(provider.get("requests"))
        if not requests:
            continue
        errors = _safe_int(provider.get("errors"))
        latency_p95 = _safe_int(provider.get("latency_ms_p95"))
        cache = provider.get("cache") or {}
        cache_ratio = _safe_float(cache.get("hit_ratio"))
        rate_limits = provider.get("rate_limits") or {}
        label = provider.get("label") or str(provider_key).title()
        provider_state = "ok"
        provider_action = "No immediate provider action."

        if errors:
            score -= min(18, errors * 4)
            provider_state = "error"
            provider_action = "Inspect failing rows, auth, model id, and rejected params."
            findings.append(
                _finding(
                    "error",
                    "Provider",
                    f"{label} has failures",
                    f"{errors} tracked {label} request{'s' if errors != 1 else ''} failed.",
                    f"{errors}/{requests} failed",
                    "Check auth, unsupported parameters, and model availability for this provider.",
                )
            )

        if latency_p95 >= 60_000:
            score -= 14
            if provider_state != "error":
                provider_state = "slow"
                provider_action = "Check model tier and streaming phase timing."
            findings.append(
                _finding(
                    "warning",
                    "Latency",
                    f"{label} p95 latency is high",
                    f"p95 latency is {_format_ms(latency_p95)} across {requests} calls.",
                    f"p95: {_format_ms(latency_p95)}",
                    "Correlate slow rows with model choice, streaming, and Fusion phase timing.",
                )
            )
        elif latency_p95 >= 20_000:
            score -= 6
            if provider_state == "ok":
                provider_state = "watch"
                provider_action = "Watch for repeated slow spikes."
            findings.append(
                _finding(
                    "info",
                    "Latency",
                    f"{label} is getting warm",
                    f"p95 latency is {_format_ms(latency_p95)}.",
                    f"p95: {_format_ms(latency_p95)}",
                    "Watch for repeated slow spikes before blaming the proxy like a monster.",
                )
            )

        if requests >= 3 and cache_ratio < 0.05:
            score -= 4
            if provider_state == "ok":
                provider_state = "watch"
                provider_action = "Confirm prompt cache behavior for this provider."
            findings.append(
                _finding(
                    "info",
                    "Cache",
                    f"{label} cache is cold",
                    f"Cache hit ratio is {_format_pct(cache_ratio)} after {requests} calls.",
                    f"Cache hit: {_format_pct(cache_ratio)}",
                    "Expected for fresh prompts; suspicious if repeated system prompts stay identical.",
                )
            )

        if rate_limits.get("status") == "unknown":
            findings.append(
                _finding(
                    "info",
                    "Rate limits",
                    f"{label} rate headers unavailable",
                    "No upstream rate-limit headers have been captured for the latest calls.",
                    "Headers: unknown",
                    "This is provider-dependent; keep visible so throttling does not sneak up on us.",
                )
            )
        else:
            remaining_tokens = _safe_int(rate_limits.get("remaining_tokens"))
            remaining_requests = _safe_int(rate_limits.get("remaining_requests"))
            if 0 < remaining_tokens <= 1_000 or 0 < remaining_requests <= 5:
                score -= 10
                if provider_state != "error":
                    provider_state = "rate-limit"
                    provider_action = "Back off or move traffic to another tier."
                findings.append(
                    _finding(
                        "warning",
                        "Rate limits",
                        f"{label} rate limit is tight",
                        "Recent upstream headers show low remaining token or request capacity.",
                        f"Tokens: {remaining_tokens}; requests: {remaining_requests}",
                        "Back off, switch model tier, or expect provider slapstick.",
                    )
                )

        provider_posture.append(
            {
                "provider": str(provider_key),
                "label": str(label),
                "state": provider_state,
                "requests": str(requests),
                "errors": str(errors),
                "p95": _format_ms(latency_p95),
                "cache": _format_pct(cache_ratio),
                "action": provider_action,
            }
        )

    bad_fusion_runs = [run for run in fusion_runs if _safe_int(run.get("errors")) > 0]
    slow_fusion_runs = [
        run for run in fusion_runs if _safe_int(run.get("duration_ms")) >= 60_000
    ]
    if bad_fusion_runs:
        score -= min(22, len(bad_fusion_runs) * 8)
        findings.append(
            _finding(
                "error",
                "Fusion",
                "Fusion has failed runs",
                f"{len(bad_fusion_runs)} recent Fusion run{'s' if len(bad_fusion_runs) != 1 else ''} reported errors.",
                f"Failed runs: {len(bad_fusion_runs)}",
                "Inspect the council trace to see whether a panel or synthesizer call failed.",
            )
        )
    if slow_fusion_runs:
        score -= min(12, len(slow_fusion_runs) * 4)
        findings.append(
            _finding(
                "warning",
                "Fusion",
                "Fusion runs are slow",
                f"{len(slow_fusion_runs)} recent Fusion run{'s' if len(slow_fusion_runs) != 1 else ''} exceeded 60s.",
                f"Slow runs: {len(slow_fusion_runs)}",
                "Parallel panel calls help; the synthesizer still decides when we get to go home.",
            )
        )

    truncated_previews = [
        request
        for request in recent_requests
        if _safe_int((request.get("stream") or {}).get("text_chars")) > 900
    ]
    if truncated_previews:
        findings.append(
            _finding(
                "healthy",
                "Streams",
                "Long responses are being bounded",
                f"{len(truncated_previews)} recent response preview{'s were' if len(truncated_previews) != 1 else ' was'} bounded for dashboard safety.",
                f"Bounded previews: {len(truncated_previews)}",
                "Content is redacted and preview-limited; full streams are not retained here.",
            )
        )

    if not findings:
        findings.append(
            _finding(
                "healthy",
                "System",
                "No obvious proxy issues",
                "Traffic is completing without recorded failures or ugly latency spikes.",
                "Primary signals clean",
                "Keep an eye on provider headers and Fusion timing as volume increases.",
            )
        )

    score = max(0, min(100, score))
    highest = _highest_severity(findings)
    severity = "attention" if highest == "error" else "watch" if score < 90 else "healthy"
    if highest == "warning" and severity == "healthy":
        severity = "watch"

    return {
        "generated_at": snapshot.get("generated_at"),
        "score": score,
        "severity": severity,
        "summary": _summary_for(severity, request_count, error_count),
        "headline": _headline_for(severity, request_count, error_count, active_count),
        "risk_summary": _risk_summary(
            findings, request_count, error_count, active_count, provider_posture
        ),
        "signals": [
            _signal("Requests", str(request_count), "neutral" if request_count else "muted"),
            _signal("Error rate", _format_pct(error_rate), "bad" if error_rate else "good"),
            _signal("Active", str(active_count), "warn" if active_count else "good"),
            _signal(
                "Fusion runs",
                str(len(fusion_runs)),
                "bad" if bad_fusion_runs else "neutral" if fusion_runs else "muted",
            ),
            _signal(
                "Cache hit",
                _format_pct(_safe_float((totals.get("cache") or {}).get("hit_ratio"))),
                "good"
                if _safe_float((totals.get("cache") or {}).get("hit_ratio")) >= 0.1
                else "muted",
            ),
        ],
        "findings": findings[:8],
        "actions": _actions_from_findings(findings, severity, request_count)[:5],
        "fix_queue": _fix_queue_from_findings(findings, provider_posture, request_count)[:6],
        "provider_posture": provider_posture[:6],
    }


def _route_guardrail_rows(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group request telemetry into route-level guardrail rows for review."""
    grouped: dict[str, dict[str, Any]] = {}
    for request in requests:
        provider = str(request.get("provider") or "unknown")
        upstream = str(request.get("upstream_provider") or provider)
        phase = str(request.get("phase") or "")
        model = str(
            request.get("display_label")
            or request.get("label")
            or request.get("model")
            or "unknown model"
        )
        key = f"{provider}:{upstream}:{phase}:{model}"
        usage = request.get("usage") or {}
        cache = request.get("cache") or {}
        stream = request.get("stream") or {}
        item = grouped.setdefault(
            key,
            {
                "label": f"{provider}/{upstream} {phase or 'request'} {model}",
                "calls": 0,
                "active": 0,
                "errors": 0,
                "tokens": 0,
                "cache_read": 0,
                "cache_base": 0,
                "chunks": 0,
                "chars": 0,
                "latencies": [],
                "latest": 0.0,
            },
        )
        item["calls"] += 1
        item["active"] += 1 if request.get("active") else 0
        item["errors"] += 1 if _request_is_error(request) else 0
        item["tokens"] += _safe_int(usage.get("total_tokens"))
        item["cache_read"] += _safe_int(cache.get("read_tokens"))
        item["cache_base"] += (
            _safe_int(usage.get("input_tokens"))
            + _safe_int(cache.get("read_tokens"))
            + _safe_int(cache.get("write_tokens"))
        )
        item["chunks"] += _safe_int(stream.get("chunks"))
        item["chars"] += (
            _safe_int(stream.get("text_chars"))
            + _safe_int(stream.get("reasoning_chars"))
            + _safe_int(stream.get("tool_chars"))
        )
        if not request.get("active"):
            item["latencies"].append(_safe_int(request.get("duration_ms")))
        item["latest"] = max(
            _safe_float(item["latest"]),
            _safe_float(request.get("ended_at") or request.get("started_at")),
        )

    rows: list[dict[str, Any]] = []
    for item in grouped.values():
        cache_base = _safe_int(item["cache_base"])
        chunks = _safe_int(item["chunks"])
        chars = _safe_int(item["chars"])
        calls = max(1, _safe_int(item["calls"]))
        item["cache_ratio"] = (_safe_int(item["cache_read"]) / cache_base) if cache_base else 0.0
        item["p95_latency"] = _percentile(item["latencies"], 0.95)
        item["brick_risk"] = chars >= 1_000 and chunks <= calls
        rows.append(item)

    return sorted(
        rows,
        key=lambda item: (
            _safe_int(item["errors"]),
            1 if item["brick_risk"] else 0,
            _safe_int(item["active"]),
            _safe_int(item["p95_latency"]),
            _safe_int(item["tokens"]),
            _safe_float(item["latest"]),
        ),
        reverse=True,
    )


def _request_is_error(request: dict[str, Any]) -> bool:
    status = _safe_int(request.get("final_status") or request.get("upstream_status"))
    return bool(request.get("error") or request.get("ok") is False or status >= 400)


def _percentile(values: list[int], percentile: float) -> int:
    clean = sorted(_safe_int(value) for value in values if _safe_int(value) >= 0)
    if not clean:
        return 0
    index = min(len(clean) - 1, max(0, int(round((len(clean) - 1) * percentile))))
    return clean[index]


def _finding(
    severity: str,
    category: str,
    title: str,
    detail: str,
    evidence: str,
    action: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "evidence": evidence,
        "action": action,
    }


def _signal(label: str, value: str, state: str) -> dict[str, str]:
    return {"label": label, "value": value, "state": state}


def _summary_for(severity: str, requests: int, errors: int) -> str:
    if severity == "attention":
        return f"{errors} failing call{'s' if errors != 1 else ''} need inspection."
    if severity == "watch":
        return "Traffic is flowing, but one or more signals deserve a look."
    if requests:
        return "Proxy telemetry looks clean for the current in-process window."
    return "Waiting for model traffic before making stronger claims."


def _headline_for(severity: str, requests: int, errors: int, active: int) -> str:
    if severity == "attention":
        return "Provider traffic needs inspection now."
    if active:
        return "Traffic is moving, with requests still in flight."
    if requests:
        return "The proxy is serving traffic in the selected process window."
    if errors:
        return "No completed traffic remains visible, but errors were recorded."
    return "No traffic yet in this dashboard process."


def _actions_from_findings(
    findings: list[dict[str, str]], severity: str, requests: int
) -> list[dict[str, str]]:
    prioritized = sorted(
        findings,
        key=lambda item: {"error": 0, "warning": 1, "info": 2, "healthy": 3}.get(
            item["severity"], 4
        ),
    )
    actions = [
        {
            "severity": item["severity"],
            "label": item["title"],
            "detail": item["action"],
        }
        for item in prioritized
        if item.get("severity") != "healthy"
    ]
    if not actions:
        detail = (
            "Let the proxy run; revisit this panel when traffic volume changes."
            if requests
            else "Send a known-good smoke prompt through the proxy."
        )
        actions.append(
            {
                "severity": severity,
                "label": "Next check",
                "detail": detail,
            }
        )
    return actions


def _risk_summary(
    findings: list[dict[str, str]],
    requests: int,
    errors: int,
    active: int,
    provider_posture: list[dict[str, str]],
) -> list[dict[str, str]]:
    severity_counts = {
        "error": sum(1 for item in findings if item.get("severity") == "error"),
        "warning": sum(1 for item in findings if item.get("severity") == "warning"),
        "info": sum(1 for item in findings if item.get("severity") == "info"),
    }
    troubled_providers = sum(
        1
        for item in provider_posture
        if item.get("state") not in {"ok", "healthy", None, ""}
    )
    return [
        {
            "label": "Blast radius",
            "value": f"{troubled_providers} provider{'s' if troubled_providers != 1 else ''}",
            "state": "bad" if errors else "warn" if troubled_providers else "good",
        },
        {
            "label": "Open failures",
            "value": str(errors),
            "state": "bad" if errors else "good",
        },
        {
            "label": "In-flight risk",
            "value": str(active),
            "state": "warn" if active else "good",
        },
        {
            "label": "Review load",
            "value": f"{severity_counts['error']}E / {severity_counts['warning']}W",
            "state": "bad"
            if severity_counts["error"]
            else "warn"
            if severity_counts["warning"]
            else "good",
        },
        {
            "label": "Evidence base",
            "value": f"{requests} call{'s' if requests != 1 else ''}",
            "state": "neutral" if requests else "muted",
        },
    ]


def _fix_queue_from_findings(
    findings: list[dict[str, str]],
    provider_posture: list[dict[str, str]],
    requests: int,
) -> list[dict[str, str]]:
    rank = {"error": 0, "warning": 1, "info": 2, "healthy": 3}
    queue: list[dict[str, str]] = []
    for index, finding in enumerate(
        sorted(findings, key=lambda item: rank.get(item.get("severity", ""), 4))
    ):
        if finding.get("severity") == "healthy":
            continue
        queue.append(
            {
                "priority": str(len(queue) + 1),
                "severity": finding.get("severity", "info"),
                "label": finding.get("title", "Review signal"),
                "why": finding.get("detail", ""),
                "next_step": finding.get("action", ""),
                "evidence": finding.get("evidence", ""),
                "source": finding.get("category", "Telemetry"),
                "impact": _impact_for(finding.get("severity", "info")),
                "effort": "Low" if index < 3 else "Medium",
            }
        )

    for provider in provider_posture:
        if provider.get("state") in {"ok", "healthy", None, ""}:
            continue
        queue.append(
            {
                "priority": str(len(queue) + 1),
                "severity": "warning" if provider.get("state") != "error" else "error",
                "label": f"{provider.get('label', 'Provider')} posture",
                "why": (
                    f"{provider.get('requests', '0')} calls, "
                    f"{provider.get('errors', '0')} errors, "
                    f"{provider.get('p95', '0ms')} p95."
                ),
                "next_step": provider.get("action", "Inspect provider routing."),
                "evidence": f"Cache {provider.get('cache', '0%')}",
                "source": "Provider",
                "impact": "Provider-specific",
                "effort": "Low",
            }
        )

    if not queue:
        queue.append(
            {
                "priority": "1",
                "severity": "healthy",
                "label": "Keep watching",
                "why": "No immediate action is visible in the current process window.",
                "next_step": (
                    "Run a known-good request and watch this panel."
                    if not requests
                    else "Let traffic accumulate before changing routing."
                ),
                "evidence": f"{requests} tracked call{'s' if requests != 1 else ''}",
                "source": "System",
                "impact": "None",
                "effort": "Low",
            }
        )
    return queue


def _impact_for(severity: str) -> str:
    if severity == "error":
        return "User-visible"
    if severity == "warning":
        return "Reliability"
    return "Operational"


def _highest_severity(findings: list[dict[str, str]]) -> str:
    order = {"healthy": 0, "info": 1, "warning": 2, "error": 3}
    return max(findings, key=lambda item: order.get(item["severity"], 0))["severity"]


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_pct(value: float) -> str:
    percent = value * 100
    return f"{percent:.0f}%" if percent >= 10 or percent == 0 else f"{percent:.1f}%"


def _format_ms(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}s"
    return f"{value}ms"
