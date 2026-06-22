# Change: Add dashboard global telemetry controls

## Phase

Phase 2 of the dashboard modernization sequence. Depends on `update-dashboard-shell-from-donor`.

## Why

Telemetry pages need shared time and grouping controls like New Relic. Operators should set a window once, then move between overview, provider, Fusion, request, and rate-limit views without losing context.

## What Changes

- Add global controls in the topbar:
  - duration dropdown
  - group-by dropdown where applicable
  - refresh icon button
  - local proxy connection status
- Persist selected controls for the browser session.
- Apply shared controls across telemetry pages.
- Remove redundant per-panel control headers when the global controls cover the same behavior.
- Define the frontend-to-backend telemetry query contract.

## Impact

- Affected specs: dashboard-telemetry-controls
- Affected code: dashboard template, dashboard JavaScript, telemetry API handlers
- Follow-up phases use these controls for all graph panels.

