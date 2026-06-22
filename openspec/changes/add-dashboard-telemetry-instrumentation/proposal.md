# Change: Add dashboard telemetry instrumentation contract

## Phase

Phase 3 of the dashboard modernization sequence. It follows the shell and global controls phases, and it becomes the data foundation for Overview, Fusion, routing, admin workbench, and quality guardrails.

## Why

The dashboard can only be as honest as the hooks feeding it. Conduit already has useful in-process telemetry, but the capture points and metric contract need to be explicit before we build more graphing and admin surfaces on top of it.

This phase turns the current hooks into a documented operator contract: what gets captured, what never gets captured, how Fusion child calls are correlated, how provider usage is normalized, and which values remain unknown instead of being fabricated because dashboards love lying when nobody is watching.

## What Changes

- Formalize the lifecycle hooks for request start, route/model selection, upstream response headers, first stream delta, stream deltas, usage, completion, failure, and Fusion child calls.
- Normalize metrics for:
  - request counts and active requests
  - status and error classes
  - latency, time to first token/chunk, and streaming shape
  - input, output, total, cache read, cache write, cache write TTL, and reasoning tokens
  - tool call and tool result activity
  - rate-limit headers
  - cost fields when pricing is configured
- Keep telemetry bounded, in-process, and no-throw in this phase.
- Keep prompt, response, credentials, and OAuth tokens redacted by default.
- Document how Conduit telemetry maps to OpenTelemetry GenAI and HTTP concepts without requiring an external exporter yet.

## Impact

- Affected specs: dashboard-telemetry-instrumentation
- Affected code later: dashboard telemetry registry, provider adapters, response adapters, Fusion invoker, dashboard API payloads, dashboard tests
- Depends on: `update-dashboard-shell-from-donor`, `add-dashboard-global-telemetry-controls`
- Enables: `add-dashboard-overview-telemetry`, `add-dashboard-fusion-observability`, `add-dashboard-model-routing-observability`, `add-dashboard-admin-workbench`
