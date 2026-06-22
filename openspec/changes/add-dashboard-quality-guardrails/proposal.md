# Change: Add dashboard quality guardrails

## Phase

Phase 6 of the dashboard modernization sequence. This phase can be started earlier in parallel with implementation, but it closes the loop after the dashboard pages exist.

## Why

The dashboard is easy to break visually and easy to pollute with generated junk. We need guardrails so "works on my tab" stops being the QA strategy. Revolutionary stuff.

## What Changes

- Add repeatable dashboard verification commands.
- Add Playwright browser checks for layout, console errors, and key interactions.
- Add tests around telemetry data shaping.
- Add repo hygiene checks for generated artifacts.
- Document the dashboard development workflow.

## Impact

- Affected specs: dashboard-quality-guardrails
- Affected code: tests, scripts, docs, CI-adjacent developer commands

