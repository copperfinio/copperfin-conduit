## ADDED Requirements

### Requirement: Telemetry lifecycle capture
The dashboard telemetry system SHALL capture the lifecycle of each proxied model request from local receipt through upstream completion or failure.

#### Scenario: Successful request completes
- **WHEN** a provider request starts, receives an upstream response, records usage, and completes successfully
- **THEN** the telemetry snapshot SHALL include one recent request record
- **AND** that record SHALL include start time, end time, duration, provider, model, status, and usage fields

#### Scenario: Failed request completes
- **WHEN** a provider request fails before or after upstream response
- **THEN** the telemetry snapshot SHALL include one recent request record
- **AND** that record SHALL include an error class or redacted error message
- **AND** the failure SHALL not disappear from summary counts

### Requirement: Normalized identity and routing fields
Request records SHALL expose stable identity and routing fields that dashboard pages can consume without parsing provider-specific payloads.

#### Scenario: Provider request is routed
- **WHEN** a request is routed to a provider and model
- **THEN** the request record SHALL include `request_id`, `provider`, `model_alias` or `model`, `operation`, and `path` when known

#### Scenario: Fusion child request is routed
- **WHEN** Fusion sends a child model call
- **THEN** the request record SHALL include `provider=fusion`
- **AND** it SHALL include `upstream_provider`, `fusion_run_id` or equivalent run id, `phase`, and a human-readable label

### Requirement: Timing metrics
Telemetry SHALL capture timing values needed to diagnose slow proxy, upstream, and streaming behavior.

#### Scenario: Non-streaming request finishes
- **WHEN** a non-streaming request completes
- **THEN** the request record SHALL include `duration_ms`

#### Scenario: Streaming request emits first content
- **WHEN** a streaming request emits its first text, reasoning, or tool delta
- **THEN** telemetry SHALL capture time-to-first-token or time-to-first-chunk as `ttft_ms` or an equivalent field

### Requirement: Usage and cache metrics
Telemetry SHALL normalize token usage across supported provider families.

#### Scenario: OpenAI-compatible usage is recorded
- **WHEN** a usage payload contains input, output, total, cached, or reasoning token fields
- **THEN** telemetry SHALL normalize those values into common usage and cache fields

#### Scenario: Anthropic usage is recorded
- **WHEN** a usage payload contains cache read, cache creation, or cache TTL token fields
- **THEN** telemetry SHALL normalize those values into common cache read/write fields
- **AND** it SHALL preserve 5-minute and 1-hour cache write buckets when available

### Requirement: Cost metrics without fabricated spend
Telemetry SHALL represent cost only when pricing data is configured and known.

#### Scenario: Pricing is unavailable
- **WHEN** usage exists but no pricing source is configured
- **THEN** `estimated_cost_usd` SHALL be null
- **AND** the payload SHALL indicate that pricing is unknown

#### Scenario: Pricing is available
- **WHEN** pricing data is configured for the provider and model
- **THEN** telemetry SHALL compute estimated request cost from normalized token usage
- **AND** it SHALL include the pricing source used for the estimate

### Requirement: Streaming and tool metrics
Telemetry SHALL track streaming shape and tool activity without storing full message content.

#### Scenario: Stream deltas arrive
- **WHEN** a stream emits text, reasoning, or tool deltas
- **THEN** telemetry SHALL increment stream counters for chunks and character counts
- **AND** it SHALL keep any preview redacted and truncated

#### Scenario: Tool calls are observed
- **WHEN** provider adapters expose tool call, tool result, or tool error events
- **THEN** telemetry SHALL count them in normalized tool counters
- **AND** it SHALL not store raw tool arguments that may contain user content or secrets

### Requirement: Error classification
Telemetry SHALL classify common proxy and provider failures so the dashboard can group errors usefully.

#### Scenario: Unsupported assistant prefill occurs
- **WHEN** a provider rejects a request because the conversation ends with an assistant prefill
- **THEN** telemetry SHALL classify the error as an unsupported assistant prefill or equivalent compatibility class

#### Scenario: Unsupported parameters occur
- **WHEN** a provider rejects a request because unsupported parameters were sent
- **THEN** telemetry SHALL classify the error as unsupported parameters or equivalent compatibility class

#### Scenario: Auth failure occurs
- **WHEN** a provider rejects credentials or auth is missing
- **THEN** telemetry SHALL classify the error as an auth-related failure without exposing credential values

### Requirement: Fusion correlation
Telemetry SHALL correlate Fusion panel and synthesizer calls into a single run.

#### Scenario: Fusion run completes
- **WHEN** Fusion executes two panel calls and one synthesizer call
- **THEN** the snapshot SHALL expose one Fusion run summary
- **AND** the run summary SHALL include the child calls ordered with panel calls before the synthesizer call

#### Scenario: Fusion child call fails
- **WHEN** one Fusion child call fails and another succeeds
- **THEN** the failed child SHALL remain visible
- **AND** the successful child SHALL remain visible
- **AND** the parent run SHALL reflect the failure

### Requirement: Privacy and redaction
Telemetry SHALL avoid storing sensitive or full conversational content by default.

#### Scenario: Request contains a secret
- **WHEN** request content, headers, or stream deltas contain secret-like text
- **THEN** telemetry previews SHALL redact the secret
- **AND** the dashboard SHALL not receive the raw secret

#### Scenario: Long content is observed
- **WHEN** request or response content exceeds the preview limit
- **THEN** telemetry SHALL truncate the preview
- **AND** it SHALL indicate that truncation occurred when the preview is exposed

### Requirement: Bounded no-throw storage
Telemetry storage SHALL be bounded and SHALL NOT break proxy traffic if telemetry itself fails.

#### Scenario: Retention limit is exceeded
- **WHEN** more events are recorded than the configured ring buffer limit
- **THEN** old events SHALL be dropped according to the retention policy
- **AND** the snapshot SHALL expose retention metadata

#### Scenario: Telemetry hook raises internally
- **WHEN** a telemetry hook encounters unexpected data
- **THEN** the hook SHALL fail closed without raising into the provider request path

### Requirement: Snapshot contract for dashboard pages
The dashboard snapshot SHALL expose stable sections for summary cards, charts, logs, and Fusion details.

#### Scenario: Dashboard requests snapshot
- **WHEN** the dashboard requests a snapshot
- **THEN** the response SHALL include totals, provider summaries, active requests, recent requests, time-series points, Fusion run summaries, and scope or retention metadata

#### Scenario: No traffic exists
- **WHEN** telemetry has no recorded traffic
- **THEN** the snapshot SHALL still return a valid payload
- **AND** numeric summaries SHALL be deterministic zero values where zero is semantically correct
- **AND** unknown values SHALL remain explicit unknown/null values

### Requirement: Standards mapping
The telemetry contract SHALL document how Conduit fields map to standard observability concepts where practical.

#### Scenario: Field mapping is reviewed
- **WHEN** an operator or developer reviews the telemetry contract
- **THEN** it SHALL be clear which fields map to GenAI model/system/operation, token usage, operation duration, HTTP request duration, and active request concepts
- **AND** the contract SHALL not require an external exporter in this phase
