## Context

Operators need a fast read on local proxy behavior while actively using Cursor or another client. The Overview page should be dense enough to debug live traffic without becoming a pretend APM product.

## Goals

- Show live request volume and active state.
- Show token volume split by input, output, cache read, cache write, and reasoning when available.
- Show latency and streaming health.
- Show provider/model route mix.
- Show recent errors by class.
- Keep every panel compact and visually aligned with the donor dashboard.

## Non-Goals

- No long-term storage analytics beyond current telemetry capability.
- No cost accounting if pricing data is unavailable.
- No provider secret display.
- No fake "green" state when data is missing.

## Candidate Overview Sections

- Summary cards:
  - Requests
  - Active
  - Token volume
  - Cache ratio
  - Errors
  - Latency p95
- Charts:
  - Request throughput
  - Token volume
  - Latency and time-to-first-token
  - Provider/model mix
  - Error mix
- Tables:
  - Recent requests
  - Current provider posture

## Data Handling

Null numeric values SHALL aggregate as zero only when zero is semantically correct. Unknown values SHALL remain unknown in labels and detail views.

## Verification

- Overview must render with no traffic.
- Overview must update after new traffic.
- Overview must make errors visible.
- Overview must not show mock traffic.

