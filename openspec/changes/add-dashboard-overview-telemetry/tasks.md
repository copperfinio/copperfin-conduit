## 1. Data Inventory

- [ ] 1.1 Inspect current in-process telemetry fields.
- [ ] 1.2 Identify missing fields needed for overview panels.
- [ ] 1.3 Define which fields are nullable, unknown, or numeric zero.

## 2. Overview API/Data Shape

- [ ] 2.1 Add or normalize an overview telemetry payload.
- [ ] 2.2 Include summary cards and bucketed series.
- [ ] 2.3 Include provider/model grouping where global group-by applies.
- [ ] 2.4 Return deterministic empty payloads for empty ranges.

## 3. Overview UI

- [ ] 3.1 Replace placeholder panels with live summary cards.
- [ ] 3.2 Add throughput, token, latency, provider mix, and error mix graphs.
- [ ] 3.3 Add recent request and provider posture panels if data is available.
- [ ] 3.4 Use donor panel chrome and chart styling.

## 4. Verification

- [ ] 4.1 Add backend tests for overview aggregation.
- [ ] 4.2 Add frontend state tests or focused browser checks for control changes.
- [ ] 4.3 Use Playwright to verify layout, empty state, and live-data state.
- [ ] 4.4 Confirm no mock telemetry remains on Overview.

