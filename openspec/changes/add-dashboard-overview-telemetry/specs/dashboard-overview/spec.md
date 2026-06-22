## ADDED Requirements

### Requirement: Live overview telemetry
The Overview page SHALL render live Conduit telemetry derived from the local proxy process.

#### Scenario: Overview with traffic
- **GIVEN** the proxy has processed requests in the selected time window
- **WHEN** the operator opens Overview
- **THEN** summary cards SHALL show request, token, cache, latency, and error metrics derived from those requests
- **AND** charts SHALL use the selected global duration and grouping controls

#### Scenario: Overview without traffic
- **GIVEN** the proxy has no traffic in the selected time window
- **WHEN** the operator opens Overview
- **THEN** cards and charts SHALL render an explicit empty state
- **AND** the page SHALL not display mock traffic

### Requirement: Overview metric cards
The Overview page SHALL provide compact metric cards for the highest-value proxy health indicators.

#### Scenario: Metric cards render
- **WHEN** Overview data loads
- **THEN** the page SHALL show request count, active request count, token volume, cache behavior, error count or rate, and latency

#### Scenario: Unknown cost
- **GIVEN** pricing data is not configured
- **WHEN** the spend card renders
- **THEN** it SHALL show an explicit unknown or unavailable value
- **AND** it SHALL not imply a calculated cost

### Requirement: Overview charts
The Overview page SHALL provide dense charts for request throughput, token volume, latency, provider or model mix, and errors.

#### Scenario: Duration changes charts
- **GIVEN** the operator changes the global duration
- **WHEN** the Overview data refreshes
- **THEN** every Overview chart SHALL use the new duration

#### Scenario: Grouping changes charts
- **GIVEN** the operator changes the global group-by selector
- **WHEN** the Overview data refreshes
- **THEN** grouped charts SHALL reflect the selected dimension

### Requirement: No mock overview data
The Overview page SHALL not include hardcoded telemetry values in production dashboard rendering.

#### Scenario: No telemetry endpoint response
- **GIVEN** the telemetry endpoint is unreachable
- **WHEN** Overview renders
- **THEN** the page SHALL show an offline or error state
- **AND** it SHALL not replace the missing data with fake values

