## Context

Copperfin Conduit has a local dashboard under `app/dashboard/`. The donor dashboard in Fair Weather Conduit demonstrates the desired operational style: compact rails, dark panels, strong accent colors, and high information density.

The current Copperfin dashboard does not need a new framework before it can be useful. The safest first step is to preserve the existing Flask/static asset delivery and replace the broken shell with a clean donor-derived structure.

## Goals

- Match the donor dashboard shell closely enough that future page work starts from the same design language.
- Keep the implementation small and inspectable.
- Avoid introducing a frontend build pipeline in this phase.
- Prevent dashboard JavaScript errors from wrecking the entire page.

## Non-Goals

- No chart redesign in this phase.
- No new telemetry storage in this phase.
- No React/Vite migration in this phase.
- No public hosted dashboard deployment changes.

## Decisions

- Decision: Use the existing Flask template and static asset stack for Phase 1.
  - Rationale: The immediate failure is layout quality, not lack of framework.
- Decision: Copy donor dimensions and token vocabulary before designing new variants.
  - Rationale: The user explicitly wants the donor dashboard copied, not creatively reinterpreted.
- Decision: Use hard layout constraints for rails and cards.
  - Rationale: Operational dashboards should not resize themselves into nonsense because a value or label got long.

## Risks

- Risk: Donor dashboard uses React/Vite while Copperfin currently uses static JavaScript.
  - Mitigation: Copy visual structure and component behavior, not framework internals.
- Risk: Existing untracked dashboard work may already contain partial attempts.
  - Mitigation: Inspect current files before editing and keep changes scoped.

## Verification

- Load `/dashboard` at desktop width.
- Confirm no console error on initial render.
- Confirm content uses full available width.
- Confirm side rails are stable while scrolling.
- Confirm missing telemetry renders a sane offline state.

