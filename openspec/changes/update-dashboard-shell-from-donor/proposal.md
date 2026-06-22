# Change: Update dashboard shell from donor layout

## Phase

Phase 1 of the dashboard modernization sequence.

## Why

The current gateway dashboard can collapse into narrow columns, huge blank content, and broken panels. The Fair Weather Conduit dashboard already has the right operational shell. We should copy that proven layout instead of inventing another cursed snowflake.

## What Changes

- Replace the current dashboard shell with a donor-aligned shell:
  - fixed icon rail
  - secondary navigation rail
  - workspace content area
  - compact topbar
  - dense card grid
- Normalize dashboard CSS tokens, gutters, panel dimensions, and responsive breakpoints.
- Make the shell resilient when telemetry is offline or partially missing.
- Keep current server-rendered dashboard stack unless a later spec explicitly changes it.
- Remove accidental layout behavior that causes content to render in a tiny left strip.

## Impact

- Affected specs: dashboard-shell
- Affected code: `app/dashboard/templates/dashboard.html`, `app/dashboard/static/dashboard.css`, `app/dashboard/static/dashboard.js`
- Follow-up phases depend on this shell being stable.

