## 1. Instrumentation Contract

- [ ] 1.1 Document the normalized request record fields in code comments or local dashboard docs.
- [ ] 1.2 Add stable event names for lifecycle milestones without forcing the UI to parse adapter internals.
- [ ] 1.3 Add explicit unknown/null handling rules for cost, rate limits, timing, and provider usage.

## 2. Hook Coverage

- [ ] 2.1 Verify request start/end hooks across Azure, Codex, Anthropic, and Fusion.
- [ ] 2.2 Verify upstream response header capture across providers.
- [ ] 2.3 Verify stream delta capture across text, reasoning, and tool deltas.
- [ ] 2.4 Add first stream delta timing so TTFT can be graphed.
- [ ] 2.5 Add tool call/result/error counters where provider adapters expose enough information.

## 3. Usage And Cost

- [ ] 3.1 Normalize Anthropic cache read/write and cache TTL token fields.
- [ ] 3.2 Normalize OpenAI/Codex cached token and reasoning token fields.
- [ ] 3.3 Add `pricing_known`, `estimated_cost_usd`, and `cost_source` fields without fabricating spend.
- [ ] 3.4 Add tests for missing/partial usage payloads.

## 4. Fusion Correlation

- [ ] 4.1 Ensure Fusion runs have a stable `fusion_run_id`.
- [ ] 4.2 Ensure child calls identify `phase=panel` or `phase=synthesizer`.
- [ ] 4.3 Ensure dashboard summaries preserve panel order and synthesizer-last ordering.
- [ ] 4.4 Ensure Fusion child failures classify errors without hiding successful sibling calls.

## 5. Privacy And Bounded Storage

- [ ] 5.1 Keep prompt and response previews redacted and truncated.
- [ ] 5.2 Add tests for split-token redaction across stream deltas.
- [ ] 5.3 Verify ring buffer retention limits are exposed in the snapshot.
- [ ] 5.4 Verify telemetry failures never break provider calls.

## 6. Verification

- [ ] 6.1 Run focused dashboard telemetry tests.
- [ ] 6.2 Run one local provider smoke path for each authenticated provider.
- [ ] 6.3 Run one Fusion `ping` smoke path and confirm two panel calls plus one synthesizer call.
- [ ] 6.4 Browser-check the dashboard snapshot consumers after implementation.
