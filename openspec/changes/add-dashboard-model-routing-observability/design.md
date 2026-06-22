## Context

Conduit supports Codex/OpenAI-style profiles, Claude/Anthropic profiles, and Fusion profiles. The README names common aliases such as `cp-gpt55-*`, `cp-opus48-*`, and `cp-fusion55`.

When a client fails, the operator needs to know whether the problem is route configuration, auth, model compatibility, provider behavior, or the client payload.

## Goals

- Show known model aliases and their provider family.
- Show endpoint compatibility: `/codex`, `/anthropic`, `/claude`, and Fusion aliases.
- Show auth readiness by provider without leaking token values.
- Show recent routing decisions with endpoint, requested model, normalized model, provider, and outcome.

## Non-Goals

- No token display.
- No direct OAuth flow changes.
- No model library editing in this phase.
- No public remote management surface.

## Verification

- Dashboard can show at least one Codex profile, one Anthropic profile, and one Fusion profile when configured.
- Auth status display does not print secrets.
- Recent route decisions match live request logs.

