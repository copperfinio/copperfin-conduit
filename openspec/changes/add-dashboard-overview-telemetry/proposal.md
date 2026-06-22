# Change: Add dashboard overview telemetry

## Phase

Phase 4 of the dashboard modernization sequence. Depends on the shell, global controls, and telemetry instrumentation phases.

## Why

The Overview page should answer the first operational question: "Is this proxy healthy and what is it doing right now?" It needs tight, real telemetry panels instead of placeholder cards.

## What Changes

- Build the Overview as the primary live telemetry surface.
- Add metric cards for requests, active calls, token volume, cache behavior, spend readiness, latency, and errors.
- Add compact graphs for throughput, latency, provider mix, and failure mix.
- Use real in-process telemetry only.
- Add empty/offline states that are useful but do not hide errors.

## Impact

- Affected specs: dashboard-overview
- Affected code: dashboard telemetry data functions, overview template sections, dashboard JavaScript, dashboard CSS
