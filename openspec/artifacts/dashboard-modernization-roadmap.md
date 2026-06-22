# Dashboard Modernization Roadmap

This roadmap orders the active OpenSpec dashboard changes so the work can be built one phase at a time.

## Phase Order

1. `update-dashboard-shell-from-donor`
   - Stabilize the app shell, rails, topbar, gutters, cards, and offline states.
   - This is the foundation. Do not start graph polish while the layout can still collapse into nonsense.

2. `add-dashboard-global-telemetry-controls`
   - Add shared duration, group-by, refresh, and connection controls.
   - Persist selections in the browser session.
   - Apply the same controls across telemetry pages.

3. `add-dashboard-telemetry-instrumentation`
   - Formalize the telemetry hook and metric contract.
   - Capture timing, usage, cache, reasoning, cost readiness, tool activity, errors, rate limits, and Fusion correlation.
   - Keep telemetry bounded, local, redacted, and no-throw.

4. `add-dashboard-overview-telemetry`
   - Build the main Overview page using live telemetry.
   - Add summary cards and core graphs for request volume, tokens, latency, provider mix, and errors.

5. `add-dashboard-fusion-observability`
   - Add Fusion run visibility.
   - Show council member calls, synthesizer calls, per-call timing, usage, and classified failures.

6. `add-dashboard-model-routing-observability`
   - Add model alias, provider readiness, auth readiness, and route decision visibility.
   - Keep credentials redacted.

7. `add-dashboard-admin-workbench`
   - Add the admin pages the proxy actually needs: models, providers, routes, logs, diagnostics, and settings.
   - Keep the donor-style left navigation and use the duration dropdown only where it applies.

8. `add-dashboard-quality-guardrails`
   - Add repeatable dashboard verification.
   - Cover Playwright smoke checks, telemetry tests, JavaScript checks, and generated artifact hygiene.

## Build Rule

Only one phase should be implemented at a time unless the user explicitly approves parallel work. Finish each phase by validating its OpenSpec change, running targeted checks, and updating the phase tasks honestly.

## Donor Rule

For visual structure, compare against the Fair Weather Conduit dashboard before inventing a new pattern. If the donor has an answer and Copperfin does not have a stronger reason to diverge, copy the donor.
