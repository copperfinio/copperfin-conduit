## Context

Copperfin Conduit is local-first infrastructure. The dashboard is not a customer marketing surface; it is the admin console for the local proxy. It should help an operator answer:

- Is Conduit running?
- Which providers are authenticated?
- Which model aliases exist?
- How are requests being routed?
- What failed recently?
- Is Fusion doing the expected council plus synthesizer work?
- What settings are active?

## Goals

- Build the admin the proxy actually needs, not a decorative dashboard.
- Keep the donor dashboard visual structure.
- Keep secrets and OAuth tokens redacted.
- Make read-only views excellent before adding write actions.
- Use explicit empty/error states instead of fallbacks.

## Non-Goals

- No remote multi-user admin in this phase.
- No secret editing in the browser.
- No OAuth token display.
- No destructive actions without a later explicit spec.
- No hosted control plane.

## Proposed Navigation

Operations:

- Overview
- Traffic
- Fusion runs
- Health

Configuration:

- Models
- Providers
- Routes
- Settings

Observability:

- Request log
- Server log
- Diagnostics

The exact labels may change during implementation, but the dashboard SHALL keep this operator-oriented grouping.

The left navigation should stay visually close to the donor dashboard: fixed icon rail, grouped text rail, compact active-row highlight, muted inactive rows, and no full-width marketing sidebar nonsense. It should feel like a cockpit, not a brochure.

## Duration Dropdown Placement

The shared duration dropdown belongs in the shell/topbar control cluster for pages that show time-windowed telemetry:

- Overview
- Traffic
- Fusion runs
- Health
- Request log
- Server log
- Diagnostics when showing recent events

The duration dropdown should not appear on static configuration pages where it does not affect the data:

- Models
- Providers, unless showing recent provider events
- Routes, unless showing recent route decisions
- Settings

This keeps the control global where it is useful and absent where it would just sit there pretending to be important.

## Admin Surface Guidance

Read-only first:

- Model aliases and upstream mapping
- Provider auth readiness
- Route matrix
- Recent request decisions
- Fusion run details
- Dashboard diagnostics

Safe actions later:

- Refresh auth status
- Reset local telemetry session
- Copy redacted diagnostics bundle
- Open CLI command hints

Anything that changes credentials, OAuth state, model aliases, or provider routing needs its own follow-up spec.

## Verification

- Navigation shows all admin sections.
- Pages with time-series data use the shared duration dropdown.
- Pages without time-series data do not show irrelevant duration controls.
- No page displays tokens, API keys, or OAuth secrets.
