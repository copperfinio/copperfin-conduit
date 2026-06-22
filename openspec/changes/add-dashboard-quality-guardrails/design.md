## Context

The dashboard is local and visual. It can fail in ways that Python tests will never see: broken CSS, bad viewport behavior, JavaScript errors, hidden panels, and generated output accidentally staged.

## Goals

- Make browser verification boring and repeatable.
- Keep generated artifacts out of commits.
- Catch JavaScript errors before shipping.
- Catch telemetry shape regressions before the UI eats them.

## Non-Goals

- No full visual snapshot approval system in this phase.
- No hosted CI redesign.
- No server lifecycle automation.

## Recommended Checks

- Python compile/import check for dashboard modules.
- JavaScript syntax check for static dashboard code.
- Pytest coverage for telemetry aggregation.
- Playwright smoke:
  - `/dashboard` loads.
  - no console errors.
  - shell uses full width.
  - global controls change data request parameters.
  - empty state renders.
- Git hygiene:
  - `preview/`, `output/`, `.playwright-cli/`, `__pycache__/`, and `.pytest_cache/` are not staged.

## Verification

This phase is complete only when the checks are documented and can be run from a clean checkout.

