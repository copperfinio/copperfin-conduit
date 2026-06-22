## Context

Current dashboard telemetry is a bounded, thread-safe, in-process registry in `app/dashboard/telemetry.py`. It already captures:

- request start and end
- upstream status and rate-limit headers
- stream text, reasoning, and tool deltas
- normalized usage for Anthropic-style and OpenAI/Codex-style payloads
- Fusion grouping by `run_id`, `phase`, and `label`
- redacted request and assistant previews

That is a good start. The missing part is a named contract that future dashboard pages and tests can rely on without spelunking through adapter code like it is a crime scene.

## Research Anchors

- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) moved to the [OpenTelemetry semantic-conventions GenAI repository path](https://github.com/open-telemetry/semantic-conventions/tree/main/docs/gen-ai), which defines common GenAI operation, system/provider, model, token usage, duration, and streaming timing concepts.
- [OpenTelemetry HTTP metrics](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/) separate server request duration and active request counters from upstream GenAI call timing.
- [New Relic AI monitoring](https://docs.newrelic.com/docs/ai-monitoring/intro-to-ai-monitoring/) emphasizes model performance, token usage, cost visibility, errors, traces, and feedback/quality monitoring.
- [LiteLLM proxy Prometheus metrics](https://docs.litellm.ai/docs/proxy/prometheus) expose request counts, spend, token metrics, provider latency, proxy overhead, time-to-first-token for streaming requests, fallback/failure metrics, and adjacent-service health.

The useful pattern across all of them is boring and correct: one request lifecycle, normalized dimensions, explicit timing, token/cost accounting, error classification, and correlation across child model calls.

## Current Hook Inventory

Current hooks:

- `record_request_start(...)`
- `record_upstream_response(...)`
- `record_stream_delta(...)`
- `record_usage(...)`
- `record_request_end(...)`
- `snapshot()`

Current call sites:

- Azure adapter and response adapter
- Codex adapter and response adapter
- Anthropic adapter and response adapters
- Fusion invoker

## Target Event Lifecycle

The instrumentation contract should model the lifecycle as:

1. `request.started`
2. `route.selected`
3. `provider.request_started`
4. `provider.response_headers`
5. `stream.first_delta`
6. `stream.delta`
7. `usage.final`
8. `request.completed` or `request.failed`
9. `fusion.run_started`
10. `fusion.child_started`
11. `fusion.child_completed` or `fusion.child_failed`
12. `fusion.run_completed` or `fusion.run_failed`

The current implementation may keep using compact method names, but the emitted data shape should be rich enough to represent these events.

## Metric Taxonomy

### Identity And Routing

- `request_id`
- `correlation_id`
- `parent_request_id`
- `fusion_run_id`
- `provider`
- `upstream_provider`
- `model_alias`
- `upstream_model`
- `operation`
- `path`
- `phase`
- `label`

### Timing

- `started_at`
- `ended_at`
- `duration_ms`
- `ttft_ms`
- `stream_duration_ms`
- `inter_chunk_ms_avg` when practical
- `inter_chunk_ms_p95` when practical

### Usage

- `input_tokens`
- `output_tokens`
- `total_tokens`
- `reasoning_tokens`
- `cache_read_tokens`
- `cache_write_tokens`
- `cache_write_5m_tokens`
- `cache_write_1h_tokens`

### Cost

- `pricing_known`
- `estimated_cost_usd`
- `cost_source`

If pricing is not configured, cost must remain `null` with `pricing_known=false`. Guessing spend is how dashboards become astrology.

### Streaming And Tools

- `stream_chunks`
- `text_chars`
- `reasoning_chars`
- `tool_chunks`
- `tool_call_count`
- `tool_result_count`
- `tool_error_count`
- redacted tool names or tool categories when available

### Outcomes

- `upstream_status`
- `final_status`
- `ok`
- `error_type`
- `error_message_redacted`
- `retryable`

Error classes should include:

- auth missing
- auth expired
- provider auth rejected
- provider unsupported assistant prefill
- provider unsupported parameters
- provider rate limited
- provider timeout
- provider 5xx
- stream adaptation failure
- proxy internal error

### Rate Limits

- request limit
- request remaining
- request reset
- token limit
- token remaining
- token reset
- retry-after

Only report rate-limit values when upstream headers provide them.

## Storage Policy

This phase keeps telemetry local and bounded:

- process-local in-memory ring buffers
- explicit retention limits in the snapshot
- reset endpoint for local testing
- no external exporter
- no persistent database

Later phases can add OpenTelemetry export, file persistence, or long-term storage if the operator story needs it.

## Privacy Policy

Telemetry must not store full prompts, full responses, OAuth tokens, API keys, cookies, or authorization headers by default.

Debug previews may exist only when:

- they are redacted
- they are truncated
- the snapshot marks them as redacted
- they are never treated as durable records

## Dashboard Contract

Dashboard pages should consume stable fields from the snapshot instead of parsing provider-specific payloads in the browser.

The snapshot should expose:

- totals
- provider summaries
- active requests
- recent requests
- time-series points
- Fusion run summaries
- retention/scope metadata
- explicit unknown values

## Non-Goals

- No external OpenTelemetry exporter in this phase.
- No persistent event store in this phase.
- No full transcript viewer.
- No secret editing or auth token display.
- No fabricated cost data.

## Verification

- Existing focused telemetry tests should continue passing.
- New tests should cover TTFT, usage normalization, Fusion correlation, redaction, bounded storage, and no-throw behavior.
- A simple `ping` request through each provider should produce one complete request record.
- A Fusion `ping` request should produce two panel child calls plus one synthesizer child call.
