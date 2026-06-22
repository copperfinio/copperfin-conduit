"""Thread-safe, in-process telemetry for the Conduit dashboard."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

PROVIDERS = ("azure", "codex", "anthropic", "fusion")
REQUEST_EVENT_LIMIT = 240
CONTENT_EVENT_LIMIT = 160
TIMESERIES_LIMIT = 360
PREVIEW_LIMIT = 900

_EVENT_NAMES = (
    "request.started",
    "route.selected",
    "provider.response_headers",
    "stream.first_delta",
    "stream.delta",
    "usage.final",
    "request.completed",
    "request.failed",
    "fusion.child.started",
    "fusion.child.completed",
    "fusion.child.failed",
)

_RATE_LIMIT_HEADER_MAP = {
    "limit_requests": (
        "x-ratelimit-limit-requests",
        "x-rate-limit-limit-requests",
        "anthropic-ratelimit-requests-limit",
    ),
    "remaining_requests": (
        "x-ratelimit-remaining-requests",
        "x-rate-limit-remaining-requests",
        "anthropic-ratelimit-requests-remaining",
    ),
    "reset_requests": (
        "x-ratelimit-reset-requests",
        "x-rate-limit-reset-requests",
        "anthropic-ratelimit-requests-reset",
    ),
    "limit_tokens": (
        "x-ratelimit-limit-tokens",
        "x-rate-limit-limit-tokens",
        "anthropic-ratelimit-tokens-limit",
    ),
    "remaining_tokens": (
        "x-ratelimit-remaining-tokens",
        "x-rate-limit-remaining-tokens",
        "anthropic-ratelimit-tokens-remaining",
    ),
    "reset_tokens": (
        "x-ratelimit-reset-tokens",
        "x-rate-limit-reset-tokens",
        "anthropic-ratelimit-tokens-reset",
    ),
    "retry_after": ("retry-after",),
}

_PROVIDER_LABELS = {
    "azure": "Azure GPT",
    "codex": "GPT / Codex",
    "anthropic": "Claude",
    "fusion": "Fusion",
}

_SENSITIVE_KEYS = {
    "authorization",
    "api-key",
    "api_key",
    "x-api-key",
    "anthropic-api-key",
    "cookie",
    "set-cookie",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "secret",
    "password",
    "key",
}


@dataclass
class RequestRecord:
    """Mutable normalized telemetry for one active or completed request.

    This is the dashboard contract. Provider adapters may have wildly different
    payloads, but the dashboard consumes this shape: identity/correlation,
    route dimensions, timing, usage/cache, cost readiness, stream counters,
    upstream outcome, and redacted previews. Unknown values stay unknown instead
    of being guessed because fake observability is just decorative lying.
    """

    request_id: str
    provider: str
    model: str
    operation: str
    started_at: float
    correlation_id: str | None = None
    parent_request_id: str | None = None
    upstream_provider: str | None = None
    phase: str | None = None
    run_id: str | None = None
    label: str | None = None
    path: str | None = None
    tier: str | None = None
    plan: str | None = None
    upstream_status: int | None = None
    final_status: int | None = None
    error: str | None = None
    error_type: str | None = None
    retryable: bool | None = None
    ended_at: float | None = None
    first_delta_at: float | None = None
    last_delta_at: float | None = None
    usage: dict[str, int] = field(default_factory=dict)
    cache: dict[str, int] = field(default_factory=dict)
    stream: dict[str, int] = field(default_factory=dict)
    rate_limits: dict[str, str] = field(default_factory=dict)
    content_preview: str = ""
    stream_preview: str = ""


class DashboardTelemetry:
    """Bounded, no-throw telemetry registry for live dashboard snapshots."""

    def __init__(self) -> None:
        """Initialize bounded in-memory telemetry buffers."""
        self._lock = Lock()
        self._started_at = time.time()
        self._active: dict[str, RequestRecord] = {}
        self._recent: deque[RequestRecord] = deque(maxlen=REQUEST_EVENT_LIMIT)
        self._content: deque[dict[str, Any]] = deque(maxlen=CONTENT_EVENT_LIMIT)
        self._timeseries: deque[dict[str, Any]] = deque(maxlen=TIMESERIES_LIMIT)
        self._sequence = 0

    def reset(self) -> None:
        """Reset in-memory telemetry, primarily for tests."""
        with self._lock:
            self._started_at = time.time()
            self._active.clear()
            self._recent.clear()
            self._content.clear()
            self._timeseries.clear()
            self._sequence = 0

    def record_request_start(
        self,
        *,
        provider: str,
        model: str | None = None,
        operation: str = "request",
        path: str | None = None,
        payload: Any = None,
        upstream_provider: str | None = None,
        phase: str | None = None,
        run_id: str | None = None,
        label: str | None = None,
        correlation_id: str | None = None,
        parent_request_id: str | None = None,
        tier: str | None = None,
        plan: str | None = None,
    ) -> str:
        """Start tracking one request and return its telemetry id."""
        try:
            provider_name = _normalize_provider(provider)
            upstream_name = (
                _normalize_provider(upstream_provider) if upstream_provider else None
            )
            request_id = uuid.uuid4().hex
            preview = preview_payload(payload)
            record = RequestRecord(
                request_id=request_id,
                provider=provider_name,
                model=_clean_text(model) or "unknown",
                operation=_clean_text(operation) or "request",
                started_at=time.time(),
                correlation_id=_clean_text(correlation_id)
                or _clean_text(run_id)
                or request_id,
                parent_request_id=_clean_text(parent_request_id),
                upstream_provider=upstream_name,
                phase=_clean_text(phase),
                run_id=_clean_text(run_id),
                label=_clean_text(label),
                path=_clean_text(path),
                tier=_clean_text(tier),
                plan=_clean_text(plan),
                content_preview=preview,
            )
            content_event = None
            if preview:
                content_event = self._content_event(
                    request_id=request_id,
                    provider=provider_name,
                    model=record.model,
                    kind="request",
                    text=preview,
                    timestamp=record.started_at,
                    upstream_provider=record.upstream_provider,
                    phase=record.phase,
                    run_id=record.run_id,
                    label=record.label,
                )
            with self._lock:
                self._active[request_id] = record
                self._sequence += 1
                if content_event is not None:
                    self._content.appendleft(content_event)
            return request_id
        except Exception:  # noqa: B902
            return ""

    def record_upstream_response(
        self,
        request_id: str | None,
        *,
        status_code: int | None = None,
        headers: Any = None,
    ) -> None:
        """Capture upstream status and real rate-limit headers if present."""
        try:
            if not request_id:
                return
            rate_limits = extract_rate_limits(headers)
            status = _safe_int(status_code)
            with self._lock:
                record = self._active.get(request_id)
                if record is None:
                    return
                if status is not None:
                    record.upstream_status = status
                if rate_limits:
                    record.rate_limits.update(rate_limits)
                self._sequence += 1
        except Exception:  # noqa: B902
            return

    def record_stream_delta(
        self,
        request_id: str | None,
        *,
        text: str | None = None,
        reasoning: str | None = None,
        tool_delta: str | None = None,
    ) -> None:
        """Capture stream counters and redacted previews without buffering full streams."""
        try:
            if not request_id:
                return
            with self._lock:
                record = self._active.get(request_id)
                if record is None:
                    return
                has_delta = bool(text or reasoning or tool_delta)
                now = time.time() if has_delta else None
                if has_delta and record.first_delta_at is None:
                    record.first_delta_at = now
                if has_delta:
                    record.last_delta_at = now
                if text:
                    _increment(record.stream, "text_chars", len(text))
                    _increment(record.stream, "chunks", 1)
                    _increment(record.stream, "text_chunks", 1)
                    record.stream_preview = _truncate(
                        _redact_text(f"{record.stream_preview}{text}"),
                        PREVIEW_LIMIT,
                    )
                if reasoning:
                    _increment(record.stream, "reasoning_chars", len(reasoning))
                    _increment(record.stream, "chunks", 1)
                    _increment(record.stream, "reasoning_chunks", 1)
                if tool_delta:
                    _increment(record.stream, "tool_chars", len(tool_delta))
                    _increment(record.stream, "tool_chunks", 1)
                    _increment(record.stream, "tool_delta_chunks", 1)
                self._sequence += 1
        except Exception:  # noqa: B902
            return

    def record_usage(
        self,
        request_id: str | None,
        *,
        provider: str,
        model: str | None,
        usage: dict[str, Any] | None,
        stop_reason: str | None = None,
        usage_provider: str | None = None,
        upstream_provider: str | None = None,
    ) -> None:
        """Record final provider usage in a normalized form."""
        try:
            if not request_id or not isinstance(usage, dict):
                return
            provider_name = _normalize_provider(provider)
            usage_provider_name = _normalize_provider(
                usage_provider or upstream_provider or provider_name
            )
            normalized = normalize_usage(usage_provider_name, usage)
            with self._lock:
                record = self._active.get(request_id)
                if record is None:
                    return
                preserve_fusion_provider = (
                    record.provider == "fusion"
                    and provider_name != "fusion"
                    and (record.run_id or record.phase in {"panel", "synthesizer"})
                )
                if not preserve_fusion_provider:
                    record.provider = provider_name
                if upstream_provider or usage_provider:
                    record.upstream_provider = usage_provider_name
                elif (
                    record.upstream_provider is None
                    and provider_name != usage_provider_name
                ):
                    record.upstream_provider = usage_provider_name
                elif (
                    record.upstream_provider is None
                    and record.provider != provider_name
                ):
                    record.upstream_provider = provider_name
                if model:
                    record.model = _clean_text(model)
                record.usage = normalized["usage"]
                record.cache = normalized["cache"]
                if stop_reason:
                    record.stream["stop_reason"] = _clean_text(stop_reason)
                self._sequence += 1
        except Exception:  # noqa: B902
            return

    def record_request_end(
        self,
        request_id: str | None,
        *,
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        """Move a request from active to recent with terminal status."""
        try:
            if not request_id:
                return
            now = time.time()
            status = _safe_int(status_code)
            with self._lock:
                record = self._active.pop(request_id, None)
                if record is None:
                    return
                record.ended_at = now
                if status is not None:
                    record.final_status = status
                if error:
                    record.error = _clean_text(error)[:240]
                record.error_type = _classify_error(
                    record.error, record.final_status or record.upstream_status
                )
                record.retryable = _is_retryable_error(
                    record.error_type, record.final_status or record.upstream_status
                )
                if record.stream_preview:
                    self._content.appendleft(
                        self._content_event(
                            request_id=record.request_id,
                            provider=record.provider,
                            model=record.model,
                            kind="assistant",
                            text=record.stream_preview,
                            timestamp=now,
                            upstream_provider=record.upstream_provider,
                            phase=record.phase,
                            run_id=record.run_id,
                            label=record.label,
                        )
                    )
                self._recent.appendleft(record)
                self._append_timeseries_locked(record)
                self._sequence += 1
        except Exception:  # noqa: B902
            return

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable dashboard snapshot."""
        try:
            with self._lock:
                active = [deepcopy(record) for record in self._active.values()]
                recent = [deepcopy(record) for record in self._recent]
                content = deepcopy(list(self._content))
                timeseries = deepcopy(list(self._timeseries))
                started_at = self._started_at
                sequence = self._sequence
            now = time.time()
            records = recent + active
            providers = {
                provider: _provider_summary(provider, records, now)
                for provider in PROVIDERS
            }
            totals = _total_summary(records)
            return {
                "generated_at": now,
                "sequence": sequence,
                "events": {
                    "lifecycle": list(_EVENT_NAMES),
                },
                "scope": {
                    "storage": "in-memory",
                    "process_scope": "per-process / single service instance",
                    "started_at": started_at,
                    "uptime_seconds": max(0.0, now - started_at),
                    "retention": {
                        "recent_requests": REQUEST_EVENT_LIMIT,
                        "content_events": CONTENT_EVENT_LIMIT,
                        "timeseries_points": TIMESERIES_LIMIT,
                    },
                },
                "totals": totals,
                "providers": providers,
                "fusion_runs": _fusion_run_summaries(records, now),
                "active_requests": [
                    serialize_record(record, now=now) for record in active
                ],
                "recent_requests": [
                    serialize_record(record, now=now) for record in recent
                ],
                "content_events": content,
                "timeseries": timeseries,
                "rate_limit_note": (
                    "Rate limits are shown only when upstream response headers expose "
                    "them; otherwise they remain unknown."
                ),
            }
        except Exception:  # noqa: B902
            return {
                "generated_at": time.time(),
                "sequence": 0,
                "scope": {"storage": "in-memory", "process_scope": "unknown"},
                "totals": _empty_totals(),
                "providers": {
                    provider: _empty_provider_summary(provider)
                    for provider in PROVIDERS
                },
                "fusion_runs": [],
                "active_requests": [],
                "recent_requests": [],
                "content_events": [],
                "timeseries": [],
                "error": "telemetry snapshot unavailable",
            }

    def _append_timeseries_locked(self, record: RequestRecord) -> None:
        self._timeseries.append(
            {
                "t": record.ended_at or time.time(),
                "provider": record.provider,
                "upstream_provider": record.upstream_provider,
                "phase": record.phase,
                "run_id": record.run_id,
                "label": record.label,
                "model": record.model,
                "operation": record.operation,
                "path": record.path,
                "correlation_id": record.correlation_id
                or record.run_id
                or record.request_id,
                "tier": record.tier,
                "plan": record.plan,
                "status_code": record.final_status or record.upstream_status,
                "error_type": record.error_type
                or _classify_error(
                    record.error, record.final_status or record.upstream_status
                ),
                "tokens": int(record.usage.get("total_tokens", 0)),
                "input_tokens": int(record.usage.get("input_tokens", 0)),
                "output_tokens": int(record.usage.get("output_tokens", 0)),
                "reasoning_tokens": int(record.usage.get("reasoning_tokens", 0)),
                "cached_tokens": int(record.cache.get("read_tokens", 0)),
                "cache_write_tokens": int(record.cache.get("write_tokens", 0)),
                "latency_ms": _latency_ms(record),
                "ttft_ms": _ttft_ms(record),
                "ok": bool(
                    not record.error
                    and _is_success(record.final_status or record.upstream_status)
                ),
                "cost": _unknown_cost(),
            }
        )

    def _content_event(
        self,
        *,
        request_id: str,
        provider: str,
        model: str,
        kind: str,
        text: str,
        timestamp: float,
        upstream_provider: str | None = None,
        phase: str | None = None,
        run_id: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        preview = _truncate(_redact_text(text), PREVIEW_LIMIT)
        return {
            "id": uuid.uuid4().hex[:16],
            "request_id": request_id,
            "provider": provider,
            "upstream_provider": upstream_provider,
            "phase": phase,
            "run_id": run_id,
            "label": label,
            "model": model,
            "kind": kind,
            "timestamp": timestamp,
            "preview": preview,
            "chars": len(text),
            "truncated": len(preview) < len(text),
            "redacted": True,
        }


telemetry = DashboardTelemetry()


def normalize_usage(provider: str, usage: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Normalize provider-specific usage payloads into common counters."""
    if provider == "anthropic":
        input_tokens = _int_from(usage, "input_tokens")
        output_tokens = _int_from(usage, "output_tokens")
        cache_read = _int_from(usage, "cache_read_input_tokens")
        cache_write = _int_from(usage, "cache_creation_input_tokens")
        cache_creation = usage.get("cache_creation")
        cache_write_5m = 0
        cache_write_1h = 0
        if isinstance(cache_creation, dict):
            cache_write_5m = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)
            cache_write_1h = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)
        total = input_tokens + output_tokens + cache_read + cache_write
        return {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "total_tokens": total,
            },
            "cache": {
                "read_tokens": cache_read,
                "write_tokens": cache_write,
                "write_5m_tokens": cache_write_5m,
                "write_1h_tokens": cache_write_1h,
            },
        }

    input_tokens = _int_from(usage, "input_tokens")
    output_tokens = _int_from(usage, "output_tokens")
    total = _int_from(usage, "total_tokens") or input_tokens + output_tokens
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    cache_read = (
        int(input_details.get("cached_tokens") or 0)
        if isinstance(input_details, dict)
        else 0
    )
    reasoning_tokens = (
        int(output_details.get("reasoning_tokens") or 0)
        if isinstance(output_details, dict)
        else 0
    )
    return {
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total,
        },
        "cache": {
            "read_tokens": cache_read,
            "write_tokens": 0,
            "write_5m_tokens": 0,
            "write_1h_tokens": 0,
        },
    }


def extract_rate_limits(headers: Any) -> dict[str, str]:
    """Extract real upstream rate-limit headers into canonical dashboard keys."""
    if headers is None:
        return {}
    try:
        header_items = dict(headers).items()
    except (TypeError, ValueError):
        return {}
    lower = {
        str(key).lower(): str(value) for key, value in header_items if value is not None
    }
    found: dict[str, str] = {}
    for canonical, names in _RATE_LIMIT_HEADER_MAP.items():
        for name in names:
            value = lower.get(name)
            if value:
                found[canonical] = value
                break
    return found


def preview_payload(payload: Any) -> str:
    """Return a redacted, truncated content preview for a request-like payload."""
    if not isinstance(payload, dict):
        return ""
    fragments: list[str] = []
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages[-6:]:
            if not isinstance(message, dict):
                continue
            role = _clean_text(message.get("role")) or "message"
            text = content_to_text(message.get("content"))
            if text:
                fragments.append(f"{role}: {text}")
    instructions = payload.get("instructions")
    if isinstance(instructions, str):
        fragments.insert(0, f"instructions: {instructions}")
    if not fragments:
        text = content_to_text(payload.get("input"))
        if text:
            fragments.append(f"input: {text}")
    return _truncate(_redact_text("\n\n".join(fragments)), PREVIEW_LIMIT)


def content_to_text(content: Any) -> str:
    """Convert common message content shapes to text for previewing."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    parts.append(part["text"])
                elif isinstance(part.get("content"), str):
                    parts.append(part["content"])
                elif part.get("type"):
                    parts.append(f"[{part.get('type')}]")
            else:
                parts.append(str(part))
        return "\n".join(parts)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(content.get("content"), str):
            return content["content"]
        return _truncate(_safe_json(content), PREVIEW_LIMIT)
    return str(content)


def serialize_record(
    record: RequestRecord, *, now: float | None = None
) -> dict[str, Any]:
    """Serialize one request record for dashboard JSON."""
    current = now or time.time()
    duration = (record.ended_at or current) - record.started_at
    cache_read = int(record.cache.get("read_tokens", 0))
    cache_base = _record_cache_base(record)
    display_label = record.label or record.model
    return {
        "id": record.request_id,
        "correlation_id": record.correlation_id or record.run_id or record.request_id,
        "parent_request_id": record.parent_request_id,
        "provider": record.provider,
        "provider_label": _PROVIDER_LABELS.get(
            record.provider, record.provider.title()
        ),
        "upstream_provider": record.upstream_provider,
        "phase": record.phase,
        "run_id": record.run_id,
        "label": record.label,
        "display_label": display_label,
        "model": record.model,
        "tier": record.tier,
        "plan": record.plan,
        "operation": record.operation,
        "path": record.path,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "duration_ms": max(0, int(duration * 1000)),
        "ttft_ms": _ttft_ms(record),
        "stream_duration_ms": _stream_duration_ms(record, now=current),
        "active": record.ended_at is None,
        "upstream_status": record.upstream_status,
        "final_status": record.final_status,
        "ok": bool(
            not record.error
            and _is_success(record.final_status or record.upstream_status)
        ),
        "error": record.error,
        "error_type": record.error_type
        or _classify_error(record.error, record.final_status or record.upstream_status),
        "retryable": record.retryable
        if record.retryable is not None
        else _is_retryable_error(
            _classify_error(record.error, record.final_status or record.upstream_status),
            record.final_status or record.upstream_status,
        ),
        "usage": dict(record.usage),
        "cache": {
            **record.cache,
            "hit_ratio": (cache_read / cache_base) if cache_base > 0 else 0.0,
        },
        "stream": _stream_summary(record, now=current),
        "cost": _unknown_cost(),
        "pricing_known": False,
        "estimated_cost_usd": None,
        "cost_source": None,
        "rate_limits": record.rate_limits or {"status": "unknown"},
        "content_preview": record.content_preview,
    }


def _provider_summary(
    provider: str, records: list[RequestRecord], now: float
) -> dict[str, Any]:
    filtered = [record for record in records if record.provider == provider]
    summary = _empty_provider_summary(provider)
    if not filtered:
        return summary
    usage = _sum_usage(filtered)
    cache = _sum_cache(filtered)
    latencies = [_latency_ms(record, now=now) for record in filtered if record.ended_at]
    success = sum(
        1
        for record in filtered
        if not record.error
        and _is_success(record.final_status or record.upstream_status)
    )
    active = sum(1 for record in filtered if record.ended_at is None)
    cache_base = sum(_record_cache_base(record) for record in filtered)
    summary.update(
        {
            "requests": len(filtered),
            "active": active,
            "errors": sum(
                1
                for record in filtered
                if record.error
                or _is_error_status(record.final_status or record.upstream_status)
            ),
            "success_rate": success / len(filtered) if filtered else 0.0,
            "latency_ms_avg": int(sum(latencies) / len(latencies)) if latencies else 0,
            "latency_ms_p95": _percentile(latencies, 0.95),
            "usage": usage,
            "cache": {
                **cache,
                "hit_ratio": (
                    (cache["read_tokens"] / cache_base) if cache_base > 0 else 0.0
                ),
            },
            "cost": _unknown_cost(),
            "pricing_known": False,
            "estimated_cost_usd": None,
            "rate_limits": _latest_rate_limits(filtered),
            "models": _model_counts(filtered),
        }
    )
    return summary


def _total_summary(records: list[RequestRecord]) -> dict[str, Any]:
    usage = _sum_usage(records)
    cache = _sum_cache(records)
    cache_base = sum(_record_cache_base(record) for record in records)
    return {
        "requests": len(records),
        "active": sum(1 for record in records if record.ended_at is None),
        "errors": sum(
            1
            for record in records
            if record.error
            or _is_error_status(record.final_status or record.upstream_status)
        ),
        "usage": usage,
        "cache": {
            **cache,
            "hit_ratio": (cache["read_tokens"] / cache_base) if cache_base > 0 else 0.0,
        },
        "cost": _unknown_cost(),
        "pricing_known": False,
        "estimated_spend_usd": None,
        "estimated_spend_note": "No pricing table is configured; token burn is reported without fabricated spend.",
    }


def _fusion_run_summaries(
    records: list[RequestRecord], now: float
) -> list[dict[str, Any]]:
    grouped: dict[str, list[RequestRecord]] = {}
    for record in records:
        if not record.run_id or record.provider != "fusion":
            continue
        grouped.setdefault(record.run_id, []).append(record)

    summaries: list[dict[str, Any]] = []
    for run_id, run_records in grouped.items():
        ordered = sorted(
            run_records,
            key=lambda item: (
                _phase_rank(item.phase),
                item.label or item.model or "",
                item.started_at,
            ),
        )
        usage = _sum_usage(ordered)
        cache = _sum_cache(ordered)
        cache_base = sum(_record_cache_base(record) for record in ordered)
        started_at = min(record.started_at for record in ordered)
        ended_values = [record.ended_at for record in ordered if record.ended_at]
        active = sum(1 for record in ordered if record.ended_at is None)
        ended_at = max(ended_values) if ended_values else None
        wall_end = now if active else ended_at or now
        errors = sum(
            1
            for record in ordered
            if record.error
            or _is_error_status(record.final_status or record.upstream_status)
        )
        summaries.append(
            {
                "run_id": run_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_ms": max(0, int((wall_end - started_at) * 1000)),
                "active": active,
                "errors": errors,
                "ok": errors == 0
                and all(
                    _is_success(record.final_status or record.upstream_status)
                    for record in ordered
                ),
                "usage": usage,
                "cache": {
                    **cache,
                    "hit_ratio": (
                        (cache["read_tokens"] / cache_base) if cache_base > 0 else 0.0
                    ),
                },
                "slowest_label": _slowest_call_label(ordered, now),
                "calls": [serialize_record(record, now=now) for record in ordered],
            }
        )
    return sorted(summaries, key=lambda item: item["started_at"], reverse=True)[:12]


def _slowest_call_label(records: list[RequestRecord], now: float) -> str | None:
    slowest: RequestRecord | None = None
    slowest_ms = -1
    for record in records:
        latency = _latency_ms(record, now=now)
        if latency > slowest_ms:
            slowest = record
            slowest_ms = latency
    return (slowest.label or slowest.model) if slowest else None


def _phase_rank(phase: str | None) -> int:
    return {"panel": 0, "synthesizer": 1}.get(phase or "", 9)


def _empty_totals() -> dict[str, Any]:
    return {
        "requests": 0,
        "active": 0,
        "errors": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        },
        "cache": {
            "read_tokens": 0,
            "write_tokens": 0,
            "write_5m_tokens": 0,
            "write_1h_tokens": 0,
            "hit_ratio": 0.0,
        },
        "cost": _unknown_cost(),
        "pricing_known": False,
        "estimated_spend_usd": None,
    }


def _empty_provider_summary(provider: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "label": _PROVIDER_LABELS.get(provider, provider.title()),
        "requests": 0,
        "active": 0,
        "errors": 0,
        "success_rate": 0.0,
        "latency_ms_avg": 0,
        "latency_ms_p95": 0,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        },
        "cache": {
            "read_tokens": 0,
            "write_tokens": 0,
            "write_5m_tokens": 0,
            "write_1h_tokens": 0,
            "hit_ratio": 0.0,
        },
        "cost": _unknown_cost(),
        "pricing_known": False,
        "estimated_cost_usd": None,
        "rate_limits": {"status": "unknown"},
        "models": {},
    }


def _record_cache_base(record: RequestRecord) -> int:
    input_tokens = int(record.usage.get("input_tokens", 0))
    if (record.upstream_provider or record.provider) == "anthropic":
        return (
            input_tokens
            + int(record.cache.get("read_tokens", 0))
            + int(record.cache.get("write_tokens", 0))
        )
    return input_tokens


def _sum_usage(records: list[RequestRecord]) -> dict[str, int]:
    return {
        "input_tokens": sum(
            int(record.usage.get("input_tokens", 0)) for record in records
        ),
        "output_tokens": sum(
            int(record.usage.get("output_tokens", 0)) for record in records
        ),
        "reasoning_tokens": sum(
            int(record.usage.get("reasoning_tokens", 0)) for record in records
        ),
        "total_tokens": sum(
            int(record.usage.get("total_tokens", 0)) for record in records
        ),
    }


def _sum_cache(records: list[RequestRecord]) -> dict[str, int]:
    return {
        "read_tokens": sum(
            int(record.cache.get("read_tokens", 0)) for record in records
        ),
        "write_tokens": sum(
            int(record.cache.get("write_tokens", 0)) for record in records
        ),
        "write_5m_tokens": sum(
            int(record.cache.get("write_5m_tokens", 0)) for record in records
        ),
        "write_1h_tokens": sum(
            int(record.cache.get("write_1h_tokens", 0)) for record in records
        ),
    }


def _latest_rate_limits(records: list[RequestRecord]) -> dict[str, str]:
    for record in sorted(records, key=lambda item: item.started_at, reverse=True):
        if record.rate_limits:
            return dict(record.rate_limits)
    return {"status": "unknown"}


def _model_counts(records: list[RequestRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.model] = counts.get(record.model, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12])


def _latency_ms(record: RequestRecord, *, now: float | None = None) -> int:
    end = record.ended_at or now or time.time()
    return max(0, int((end - record.started_at) * 1000))


def _ttft_ms(record: RequestRecord) -> int | None:
    if record.first_delta_at is None:
        return None
    return max(0, int((record.first_delta_at - record.started_at) * 1000))


def _stream_duration_ms(record: RequestRecord, *, now: float | None = None) -> int | None:
    if record.first_delta_at is None:
        return None
    end = record.last_delta_at or record.ended_at or now or time.time()
    return max(0, int((end - record.first_delta_at) * 1000))


def _stream_summary(record: RequestRecord, *, now: float | None = None) -> dict[str, Any]:
    stream = dict(record.stream)
    stream.setdefault("chunks", 0)
    stream.setdefault("text_chunks", 0)
    stream.setdefault("reasoning_chunks", 0)
    stream.setdefault("tool_chunks", 0)
    stream.setdefault("tool_delta_chunks", 0)
    stream.setdefault("tool_call_count", 0)
    stream.setdefault("tool_result_count", 0)
    stream.setdefault("tool_error_count", 0)
    stream["ttft_ms"] = _ttft_ms(record)
    stream["duration_ms"] = _stream_duration_ms(record, now=now)
    return stream


def _classify_error(error: str | None, status: int | None) -> str | None:
    code = _safe_int(status)
    message = (error or "").lower()
    if not message and not _is_error_status(code):
        return None
    if "assistant message prefill" in message:
        return "unsupported_assistant_prefill"
    if "unsupported" in message or "parameter" in message or "prefill" in message:
        return "unsupported_parameters"
    if code in {401, 403} or any(
        fragment in message
        for fragment in (
            "unauthorized",
            "invalid api key",
            "expired",
            "credential",
            "auth",
        )
    ):
        return "auth"
    if code == 429 or "rate limit" in message or "too many requests" in message:
        return "rate_limit"
    if code in {408, 504} or any(
        fragment in message for fragment in ("timeout", "timed out", "deadline")
    ):
        return "timeout"
    if any(
        fragment in message
        for fragment in ("connection", "network", "socket", "dns", "reset by peer")
    ):
        return "network"
    if code is not None and code >= 500:
        return "provider_5xx"
    if code is not None and code >= 400:
        return "client_4xx"
    return "unknown"


def _is_retryable_error(error_type: str | None, status: int | None) -> bool:
    if error_type in {"rate_limit", "timeout", "provider_5xx", "network"}:
        return True
    code = _safe_int(status)
    return code is not None and code in {408, 429, 500, 502, 503, 504}


def _unknown_cost() -> dict[str, Any]:
    return {
        "estimated_usd": None,
        "pricing_known": False,
        "source": None,
    }


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return int(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def _normalize_provider(provider: str | None) -> str:
    candidate = (provider or "unknown").strip().lower()
    if candidate in {"claude", "anthropic"}:
        return "anthropic"
    if candidate in {"gpt", "openai", "chatgpt", "codex"}:
        return "codex"
    if candidate in PROVIDERS:
        return candidate
    return candidate or "unknown"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_from(values: dict[str, Any], key: str) -> int:
    try:
        return int(values.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _increment(target: dict[str, int], key: str, amount: int) -> None:
    target[key] = int(target.get(key, 0)) + amount


def _is_success(status: int | None) -> bool:
    return status is None or 200 <= int(status) < 400


def _is_error_status(status: int | None) -> bool:
    return status is not None and int(status) >= 400


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _safe_json(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _redact_text(text: str) -> str:
    redacted = text
    redacted = _redact_key_value_text(redacted)
    redacted = _redact_token_like_text(redacted)
    return redacted


def _redact_key_value_text(text: str) -> str:
    import re

    secret_key_pattern = (
        r"authorization|api[-_ ]?key|access[-_ ]?token|"
        r"refresh[-_ ]?token|password|secret"
    )
    pattern = re.compile(rf"(?i)({secret_key_pattern})(\s*[:=]\s*)([^\s,;\]}}]+)")
    return pattern.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text
    )


def _redact_token_like_text(text: str) -> str:
    import re

    patterns = [
        r"sk-[A-Za-z0-9_-]{12,}",
        r"sk-ant-[A-Za-z0-9_-]{12,}",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}",
        r"conduit_[A-Fa-f0-9]{16,}",
    ]
    redacted = text
    for pattern in patterns:
        redacted = re.sub(pattern, "[redacted]", redacted)
    return redacted


def stable_id(value: str) -> str:
    """Return a short stable identifier for UI grouping."""
    return hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:12]
