## Context

The dashboard is an operator console for a local process. Time windows are the primary investigation handle: "what happened in the last 3 hours" or "what happened while Cursor made that request."

The controls should feel global, not repeated inside every panel like somebody lost a fight with copy-paste.

## Goals

- Make time window and grouping sticky across dashboard pages.
- Keep controls compact enough for the donor topbar.
- Avoid duplicate "custom from/to" boxes unless a later custom range interaction needs them.
- Use browser-local time for labels.

## Non-Goals

- No full query builder.
- No saved dashboards.
- No server-side user preferences.
- No multi-user dashboard state.

## Decisions

- Decision: Store control state in `sessionStorage`.
  - Rationale: The dashboard is local-first and session-scoped.
- Decision: Start with fixed duration presets plus session.
  - Rationale: This maps to current local telemetry without overbuilding.
- Decision: Use query params for telemetry reads.
  - Rationale: This keeps endpoints easy to inspect and test.

## Telemetry Query Contract

Telemetry APIs SHOULD accept:

```text
window_seconds=<integer or all>
group_by=<provider|upstream|model|phase|status|none>
bucket_seconds=<integer optional>
```

If the API later supports exact ranges, it SHOULD accept:

```text
from=<utc iso timestamp>
to=<utc iso timestamp>
```

The frontend SHALL omit unsupported params rather than send junk and hope.

## Verification

- Changing duration refetches relevant panels.
- Changing group-by refetches relevant panels.
- Refresh triggers a refetch without resetting selected controls.
- Opening another dashboard page preserves session controls.

