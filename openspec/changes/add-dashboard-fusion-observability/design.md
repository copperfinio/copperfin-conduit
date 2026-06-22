## Context

Fusion currently coordinates multiple model calls: council members plus a synthesizer. The dashboard should make that orchestration legible.

This is not a generic APM view. It is a local proxy debugging cockpit for "why did Cursor get that answer, why did that model fail, and where did the time go?"

## Goals

- Show one Fusion run as a parent event with child call events.
- Show council member roles and synthesizer role.
- Show per-call model ID, provider, start time, duration, usage, and outcome.
- Show aggregate Fusion duration and the slowest child call.
- Identify error class without leaking prompt or response content.

## Non-Goals

- No full transcript viewer by default.
- No prompt content display unless a later secure debug mode is approved.
- No external trace backend.
- No long-term retention policy in this phase.

## Data Model Guidance

Fusion telemetry SHOULD represent:

```text
fusion_run_id
phase: panel|synthesizer
role
provider
model
started_at
duration_ms
status
error_type
input_tokens
output_tokens
cache_read_tokens
cache_write_tokens
reasoning_tokens
```

Existing telemetry fields may be reused when they map cleanly.

## Verification

- A `ping` Fusion request should produce one parent run and the expected child calls.
- The dashboard should show timing for each child call.
- The dashboard should show failure class when one child fails.
