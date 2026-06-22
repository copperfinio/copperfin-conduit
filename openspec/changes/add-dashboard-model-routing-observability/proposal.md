# Change: Add dashboard model routing observability

## Phase

Phase 5 of the dashboard modernization sequence. Can run after the Overview phase; benefits from Fusion observability.

## Why

Conduit exposes aliases and provider routes. Operators need to see which model IDs are available, which upstream they target, which auth source they require, and why a request routed the way it did.

## What Changes

- Add dashboard views for model aliases, provider readiness, route mapping, and auth state.
- Show model availability without exposing secrets.
- Show whether Codex/OpenAI auth and Anthropic/Claude auth are present, expired, or unknown.
- Show recent routing decisions by endpoint and model alias.
- Make route problems visible without relying on raw logs.

## Impact

- Affected specs: dashboard-model-routing-observability
- Affected code: model profile/config readers, auth status reporting, dashboard API, dashboard UI

