"""Focused tests for dashboard telemetry snapshots."""

from __future__ import annotations

import pytest

from app.dashboard.app import create_dashboard_app
from app.dashboard.blueprint import build_ops_review
from app.dashboard.telemetry import telemetry
from app.fusion.invoker import FusionModelInvoker, FusionTextResult


@pytest.fixture(autouse=True)
def reset_dashboard_telemetry():
    """Keep the process-global dashboard telemetry isolated per test."""
    telemetry.reset()
    yield
    telemetry.reset()


def test_fusion_invocations_snapshot_as_three_distinct_model_rows(monkeypatch):
    """Fusion panel and synthesizer internals appear as separate dashboard rows."""
    invoker = FusionModelInvoker.__new__(FusionModelInvoker)
    run_id = "fusion-run-1"

    def fake_provider_for_model(model):
        if model == "cp-gpt55-xhigh":
            return "codex"
        if model == "cp-opus48-xhigh":
            return "anthropic"
        raise AssertionError(f"unexpected model {model}")

    def fake_invoke_codex_text(*, payload, downstream_headers, telemetry_id=""):
        del payload, downstream_headers
        telemetry.record_upstream_response(
            telemetry_id,
            status_code=200,
            headers={"x-ratelimit-remaining-tokens": "1234"},
        )
        telemetry.record_stream_delta(telemetry_id, text="gpt panel")
        return FusionTextResult(
            text="gpt panel",
            usage={
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "input_tokens_details": {"cached_tokens": 80},
            },
            stop_reason="completed",
        )

    def fake_invoke_anthropic_text(*, payload, downstream_headers, telemetry_id=""):
        del downstream_headers
        telemetry.record_upstream_response(
            telemetry_id,
            status_code=200,
            headers={"anthropic-ratelimit-tokens-remaining": "456"},
        )
        telemetry.record_stream_delta(telemetry_id, text=payload["model"])
        return FusionTextResult(
            text=payload["model"],
            usage={
                "input_tokens": 100,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 50,
                "output_tokens": 25,
            },
            stop_reason="end_turn",
        )

    monkeypatch.setattr(invoker, "provider_for_model", fake_provider_for_model)
    monkeypatch.setattr(invoker, "_invoke_codex_text", fake_invoke_codex_text)
    monkeypatch.setattr(invoker, "_invoke_anthropic_text", fake_invoke_anthropic_text)

    invoker.invoke_text(
        model="cp-gpt55-xhigh",
        payload={
            "model": "cp-gpt55-xhigh",
            "messages": [{"role": "user", "content": "go"}],
        },
        downstream_headers={},
        phase="panel",
        run_id=run_id,
        label="Panel - GPT 5.5",
    )
    invoker.invoke_text(
        model="cp-opus48-xhigh",
        payload={
            "model": "cp-opus48-xhigh",
            "messages": [{"role": "user", "content": "go"}],
        },
        downstream_headers={},
        phase="panel",
        run_id=run_id,
        label="Panel - Opus 4.8",
    )
    invoker.invoke_text(
        model="cp-opus48-xhigh",
        payload={
            "model": "cp-opus48-xhigh",
            "messages": [{"role": "user", "content": "synthesize"}],
        },
        downstream_headers={},
        phase="synthesizer",
        run_id=run_id,
        label="Synthesizer - Opus 4.8",
    )

    snapshot = telemetry.snapshot()
    records = snapshot["recent_requests"]

    assert len(records) == 3
    assert {record["provider"] for record in records} == {"fusion"}
    assert {record["run_id"] for record in records} == {run_id}
    assert {record["label"] for record in records} == {
        "Panel - GPT 5.5",
        "Panel - Opus 4.8",
        "Synthesizer - Opus 4.8",
    }
    assert {record["display_label"] for record in records} == {
        "Panel - GPT 5.5",
        "Panel - Opus 4.8",
        "Synthesizer - Opus 4.8",
    }

    by_label = {record["label"]: record for record in records}
    gpt = by_label["Panel - GPT 5.5"]
    panel_opus = by_label["Panel - Opus 4.8"]
    synthesizer_opus = by_label["Synthesizer - Opus 4.8"]

    assert gpt["upstream_provider"] == "codex"
    assert gpt["usage"] == {
        "input_tokens": 100,
        "output_tokens": 10,
        "reasoning_tokens": 0,
        "total_tokens": 110,
    }
    assert gpt["cache"]["read_tokens"] == 80
    assert gpt["cache"]["hit_ratio"] == pytest.approx(0.8)
    assert gpt["rate_limits"]["remaining_tokens"] == "1234"

    assert panel_opus["upstream_provider"] == "anthropic"
    assert panel_opus["usage"] == {
        "input_tokens": 100,
        "output_tokens": 25,
        "reasoning_tokens": 0,
        "total_tokens": 1075,
    }
    assert panel_opus["cache"]["read_tokens"] == 900
    assert panel_opus["cache"]["write_tokens"] == 50
    assert panel_opus["cache"]["hit_ratio"] == pytest.approx(900 / 1050)
    assert panel_opus["rate_limits"]["remaining_tokens"] == "456"

    assert synthesizer_opus["upstream_provider"] == "anthropic"
    assert synthesizer_opus["usage"]["total_tokens"] == 1075
    assert synthesizer_opus["cache"]["read_tokens"] == 900

    assert snapshot["providers"]["fusion"]["requests"] == 3
    assert snapshot["providers"]["fusion"]["cache"]["hit_ratio"] == pytest.approx(
        (80 + 900 + 900) / (100 + 1050 + 1050)
    )
    assert [point["label"] for point in snapshot["timeseries"]] == [
        "Panel - GPT 5.5",
        "Panel - Opus 4.8",
        "Synthesizer - Opus 4.8",
    ]

    fusion_runs = snapshot["fusion_runs"]
    assert len(fusion_runs) == 1
    assert fusion_runs[0]["run_id"] == run_id
    assert fusion_runs[0]["usage"]["total_tokens"] == 2260
    assert fusion_runs[0]["cache"]["hit_ratio"] == pytest.approx(
        (80 + 900 + 900) / (100 + 1050 + 1050)
    )
    assert [call["display_label"] for call in fusion_runs[0]["calls"]] == [
        "Panel - GPT 5.5",
        "Panel - Opus 4.8",
        "Synthesizer - Opus 4.8",
    ]


def test_usage_callback_preserves_fusion_provider_for_synthesizer_call():
    """Codex/Anthropic stream callbacks must keep synthesizer rows in Fusion."""
    request_id = telemetry.record_request_start(
        provider="fusion",
        upstream_provider="codex",
        model="cp-gpt55-xfast",
        operation="codex-request",
        phase="synthesizer",
        run_id="fusion-run-callback",
        label="Synthesizer - GPT 5.5",
    )
    telemetry.record_usage(
        request_id,
        provider="codex",
        model="gpt-5.5",
        usage={
            "input_tokens": 40,
            "output_tokens": 7,
            "total_tokens": 47,
            "input_tokens_details": {"cached_tokens": 20},
        },
        stop_reason="completed",
    )
    telemetry.record_request_end(request_id, status_code=200)

    snapshot = telemetry.snapshot()
    record = snapshot["recent_requests"][0]
    assert record["provider"] == "fusion"
    assert record["upstream_provider"] == "codex"
    assert record["phase"] == "synthesizer"
    assert record["label"] == "Synthesizer - GPT 5.5"
    assert record["usage"]["total_tokens"] == 47
    assert record["cache"]["read_tokens"] == 20
    assert snapshot["providers"]["fusion"]["requests"] == 1
    assert snapshot["providers"]["codex"]["requests"] == 0
    assert snapshot["fusion_runs"][0]["calls"][0]["provider"] == "fusion"


def test_fusion_synthesizer_call_joins_same_run_and_orders_last():
    """The final synthesizer model call is grouped into the same Fusion run."""
    run_id = "fusion-run-synthesizer"
    for phase, label, upstream in (
        ("panel", "Panel - GPT 5.5", "codex"),
        ("panel", "Panel - Opus 4.8", "anthropic"),
        ("synthesizer", "Synthesizer - Opus 4.8", "anthropic"),
    ):
        request_id = telemetry.record_request_start(
            provider="fusion",
            upstream_provider=upstream,
            model=label,
            operation="fusion-call",
            phase=phase,
            run_id=run_id,
            label=label,
        )
        telemetry.record_usage(
            request_id,
            provider="fusion",
            usage_provider=upstream,
            model=label,
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        telemetry.record_request_end(request_id, status_code=200)

    snapshot = telemetry.snapshot()
    assert len(snapshot["fusion_runs"]) == 1
    run = snapshot["fusion_runs"][0]
    assert run["run_id"] == run_id
    assert [call["phase"] for call in run["calls"]] == [
        "panel",
        "panel",
        "synthesizer",
    ]
    assert [call["display_label"] for call in run["calls"]] == [
        "Panel - GPT 5.5",
        "Panel - Opus 4.8",
        "Synthesizer - Opus 4.8",
    ]
    assert run["usage"]["total_tokens"] == 45
    assert snapshot["providers"]["fusion"]["requests"] == 3


def test_stream_preview_redacts_secret_split_across_deltas():
    """A secret streamed across multiple deltas is redacted in dashboard content."""
    request_id = telemetry.record_request_start(
        provider="codex",
        model="gpt-5.5",
        operation="codex-request",
    )
    telemetry.record_stream_delta(request_id, text="Authorization: Bearer sk-")
    telemetry.record_stream_delta(request_id, text="abcdef0123456789ABCDEF")
    telemetry.record_request_end(request_id, status_code=200)

    snapshot = telemetry.snapshot()
    assistant_events = [
        event for event in snapshot["content_events"] if event["kind"] == "assistant"
    ]
    assert assistant_events, "expected an assistant content event"
    preview = assistant_events[0]["preview"]
    assert "abcdef0123456789ABCDEF" not in preview
    assert "[redacted]" in preview
    assert assistant_events[0]["redacted"] is True


def test_ops_review_reports_no_traffic_without_crashing():
    """The ops review gives a useful empty-state instead of pretending."""
    review = build_ops_review(telemetry.snapshot())

    assert review["severity"] == "watch"
    assert review["score"] < 100
    assert review["signals"][0]["label"] == "Requests"
    assert review["signals"][0]["value"] == "0"
    assert review["findings"][0]["title"] == "No traffic observed"
    assert review["findings"][0]["category"] == "Telemetry"
    assert review["findings"][0]["evidence"] == "Requests: 0"
    assert review["actions"][0]["label"] == "No traffic observed"
    assert review["risk_summary"][0]["label"] == "Blast radius"
    assert review["risk_summary"][-1]["value"] == "0 calls"
    assert review["fix_queue"][0]["label"] == "No traffic observed"
    assert review["fix_queue"][0]["priority"] == "1"


def test_ops_review_surfaces_provider_errors_and_slow_latency():
    """Failures and slow provider calls should become actionable findings."""
    request_id = telemetry.record_request_start(
        provider="anthropic",
        model="cp-opus48-xhigh",
        operation="anthropic-request",
    )
    telemetry.record_upstream_response(request_id, status_code=502)
    telemetry.record_request_end(
        request_id,
        status_code=502,
        error="provider exploded in the traditional manner",
    )

    snapshot = telemetry.snapshot()
    snapshot["providers"]["anthropic"]["latency_ms_p95"] = 65_000
    review = build_ops_review(snapshot)
    titles = {finding["title"] for finding in review["findings"]}

    assert review["severity"] == "attention"
    assert "Upstream errors present" in titles
    assert "Claude has failures" in titles
    assert "Claude p95 latency is high" in titles
    assert any(action["label"] == "Upstream errors present" for action in review["actions"])
    assert review["risk_summary"][0]["state"] == "bad"
    assert review["fix_queue"][0]["severity"] == "error"
    assert review["fix_queue"][0]["impact"] == "User-visible"
    assert review["provider_posture"][0]["state"] == "error"


def test_ops_review_surfaces_route_guardrail_findings():
    """The ops review should flag bad route lanes and buffered streams."""
    failing_id = telemetry.record_request_start(
        provider="anthropic",
        model="cp-opus48-xhigh",
        operation="anthropic-request",
    )
    telemetry.record_upstream_response(failing_id, status_code=500)
    telemetry.record_request_end(
        failing_id,
        status_code=500,
        error="provider rejected request",
    )

    stream_id = telemetry.record_request_start(
        provider="codex",
        model="cp-gpt55-xhigh",
        operation="codex-request",
    )
    telemetry.record_stream_delta(stream_id, text="x" * 1_200)
    telemetry.record_usage(
        stream_id,
        provider="codex",
        model="cp-gpt55-xhigh",
        usage={"input_tokens": 1_500, "output_tokens": 20, "total_tokens": 1_520},
    )
    telemetry.record_request_end(stream_id, status_code=200)

    review = build_ops_review(telemetry.snapshot())
    titles = {finding["title"] for finding in review["findings"]}

    assert "Routes are breaching error SLO" in titles
    assert "Possible buffered stream lanes" in titles
    assert any(
        action["label"] == "Routes are breaching error SLO"
        for action in review["actions"]
    )


def test_dashboard_routes_render_shell_and_snapshot_payload():
    """The local dashboard shell and JSON routes should stay wired together."""
    request_id = telemetry.record_request_start(
        provider="fusion",
        upstream_provider="anthropic",
        model="cp-opus48-xhigh",
        operation="fusion-call",
        phase="synthesizer",
        run_id="fusion-dashboard-test",
        label="Synthesizer - Opus 4.8",
    )
    telemetry.record_usage(
        request_id,
        provider="fusion",
        usage_provider="anthropic",
        model="cp-opus48-xhigh",
        usage={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
    )
    telemetry.record_request_end(request_id, status_code=200)

    client = create_dashboard_app().test_client()
    html_response = client.get("/dashboard/")
    snapshot_response = client.get("/dashboard/api/snapshot")
    review_response = client.get("/dashboard/api/ops-review")

    assert html_response.status_code == 200
    html = html_response.get_data(as_text=True)
    assert 'id="phase-chart"' in html
    assert 'id="efficiency-chart"' in html
    assert 'id="route-matrix"' in html
    assert 'id="window-select"' in html
    assert 'id="group-select"' in html
    assert 'id="provider-posture"' in html
    assert 'id="posture-window"' in html
    assert 'id="provider-runway"' in html
    assert 'id="runway-window"' in html
    assert 'id="provider-readiness"' in html
    assert 'id="readiness-window"' in html
    assert 'id="rate-limits"' in html
    assert 'id="heatmap-window"' in html
    assert 'id="heatmap-summary"' in html
    assert 'id="traffic-heatmap"' in html
    assert 'id="slo-window"' in html
    assert 'id="route-slo-summary"' in html
    assert 'id="route-slo-board"' in html
    assert 'id="group-chart"' in html
    assert 'id="group-pressure"' in html
    assert 'id="execution-timeline"' in html
    assert 'id="timeline-window"' in html
    assert 'id="stream-summary"' in html
    assert 'id="stream-shape"' in html
    assert 'id="stream-window"' in html
    assert 'id="latency-bands-chart"' in html
    assert 'id="latency-band-summary"' in html
    assert 'id="failure-taxonomy"' in html
    assert 'id="failure-taxonomy-count"' in html
    assert 'id="fingerprint-window"' in html
    assert 'id="fingerprint-summary"' in html
    assert 'id="failure-fingerprints"' in html
    assert 'id="contention-map"' in html
    assert 'id="contention-actions"' in html
    assert 'id="contention-window"' in html
    assert 'id="ops-headline"' in html
    assert 'id="ops-actions"' in html
    assert 'id="ops-risk-summary"' in html
    assert 'id="ops-fix-queue"' in html
    assert 'id="ops-provider-posture"' in html
    assert 'data-chart-key="token"' in html
    assert 'data-chart-mode="bar"' in html
    assert 'class="menu-rail"' in html

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.get_json()
    assert snapshot["ops_review"]["signals"]
    assert snapshot["fusion_runs"][0]["calls"][0]["phase"] == "synthesizer"

    assert review_response.status_code == 200
    assert review_response.get_json()["score"] >= 0
