# Change: Add dashboard Fusion observability

## Phase

Phase 5 of the dashboard modernization sequence. Depends on telemetry controls, the instrumentation contract, and overview data shape.

## Why

Fusion is the most interesting and most failure-prone path in the proxy. Operators need to see the council members, synthesizer, timing, token usage, and failures without digging through raw logs like it is 2009 and we are paid by the grep.

## What Changes

- Add Fusion-specific dashboard panels.
- Show council member calls, synthesizer call, model IDs, timing, usage, cache behavior, and errors.
- Distinguish panel calls from synthesizer calls.
- Surface known error classes such as unsupported assistant prefill, unsupported params, auth failures, provider errors, and stream adaptation failures.
- Keep message content redacted by default.

## Impact

- Affected specs: dashboard-fusion-observability
- Affected code: Fusion telemetry capture, dashboard API data shape, Fusion dashboard panels
