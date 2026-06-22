# Change: Add dashboard admin workbench

## Phase

Phase 6 of the dashboard modernization sequence. It follows core telemetry and routing visibility, and it precedes final quality guardrails.

## Why

The dashboard should not only show graphs. It should be a local admin workbench for running Conduit: model aliases, providers, auth readiness, route behavior, logs, diagnostics, and safe local settings. If operators still have to grep logs and remember CLI commands for basic status, the dashboard is only half a tool.

## What Changes

- Add an admin-oriented dashboard structure with pages for:
  - Overview
  - Traffic
  - Fusion runs
  - Models
  - Providers and auth readiness
  - Routes
  - Request log
  - Diagnostics
  - Settings
- Keep sensitive values redacted.
- Prefer read-only visibility first, then explicit safe actions.
- Place admin pages in the donor-style left navigation.
- Reuse the global duration dropdown on pages where time filtering applies.

## Impact

- Affected specs: dashboard-admin-workbench
- Affected code: dashboard navigation, dashboard pages, dashboard API endpoints, CLI/service status helpers
- Depends on: `update-dashboard-shell-from-donor`, `add-dashboard-global-telemetry-controls`

