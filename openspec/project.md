# Project Context

## Purpose

Copperfin Conduit is a local-first LLM proxy for API-first AI coding tools. It lets clients such as Cursor send OpenAI-compatible or Anthropic-compatible requests through subscription-backed ChatGPT/Codex and Claude auth, while preserving streaming, tool calls, image input handling, usage accounting, and Fusion orchestration.

The dashboard is an operator surface for the local proxy. It must make live proxy behavior visible without exposing secrets or pretending mock data is real.

## Product Principles

- Local-first: durable user state belongs under `~/.conduit`, not in the repo.
- Honest observability: show what happened, do not hide errors behind fallbacks.
- No mock telemetry in production views.
- Redact sensitive values by default.
- Preserve Cursor compatibility while keeping Conduit-specific behavior explicit.
- Prefer clean implementation over compatibility with throwaway dashboard experiments.

## Technical Context

- Python package: `copperfin-conduit`
- CLI: `conduit`
- Dashboard code: `app/dashboard/`
- Current dashboard stack: server-rendered Flask template, static CSS, static JavaScript
- Donor visual target: Fair Weather Conduit dashboard in `C:\Dev\fair-weather-mono\apps\conduit\conduit-dashboard`
- Generated scratch folders such as `preview/`, `output/`, `.playwright-cli/`, and `__pycache__/` must not be treated as source.

## Dashboard Design Direction

The dashboard SHALL use a compact New Relic-inspired operational style, but the immediate design source is the Fair Weather Conduit dashboard:

- left icon rail
- secondary navigation rail
- top header with global controls
- dense cards and graph panels
- dark panel backgrounds
- cyan, green, orange, purple, and red accent vocabulary
- professional spacing with no accidental huge blank content areas

The implementation SHOULD copy reusable structure, spacing, and visual rhythm from the donor dashboard before inventing new layout patterns. If a choice is not obvious, prefer the donor dashboard.

## Validation Expectations

Dashboard UI changes require:

- JavaScript syntax check or equivalent build check
- Python import/compile check for touched dashboard modules
- Playwright browser verification for key pages
- Screenshot review when layout or graphing changes
- Git hygiene check before finishing

