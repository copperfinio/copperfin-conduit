## ADDED Requirements

### Requirement: Global telemetry controls
The dashboard SHALL provide global telemetry controls in the topbar for duration, grouping, refresh, and connection status.

#### Scenario: Controls render in the topbar
- **WHEN** an operator opens a telemetry page
- **THEN** the duration selector SHALL render in the topbar
- **AND** the refresh action SHALL render as an icon button
- **AND** the connection status SHALL render in the same control cluster

#### Scenario: Duration dropdown contains operational presets
- **WHEN** the duration selector is opened
- **THEN** it SHALL include `Session`, `5 minutes`, `15 minutes`, `1 hour`, and `3 hours`
- **AND** it SHOULD include longer windows when the backing telemetry can support them

#### Scenario: Grouping is page-aware
- **GIVEN** a telemetry page supports grouping
- **WHEN** the page renders
- **THEN** the group-by selector SHALL be visible
- **AND** changing it SHALL refetch or recompute the page data

#### Scenario: Grouping is not applicable
- **GIVEN** a telemetry page does not support grouping
- **WHEN** the page renders
- **THEN** the group-by selector SHALL be hidden or disabled without leaving dead space

### Requirement: Session-sticky telemetry state
Telemetry control selections SHALL persist within the browser session and SHALL be shared by telemetry pages.

#### Scenario: Duration survives navigation
- **GIVEN** an operator selects `3 hours`
- **WHEN** the operator navigates to another telemetry page
- **THEN** that page SHALL use `3 hours` as its active duration

#### Scenario: Refresh preserves state
- **GIVEN** an operator has selected a duration and group-by value
- **WHEN** the operator clicks refresh
- **THEN** the page SHALL refetch data using the existing selected values
- **AND** the controls SHALL not reset

### Requirement: Valid telemetry query parameters
Dashboard telemetry requests SHALL send only supported query parameters and SHALL not rely on client-side fallbacks to hide unsupported API behavior.

#### Scenario: Duration preset request
- **WHEN** an operator selects a duration preset
- **THEN** the telemetry request SHALL include the corresponding `window_seconds` value

#### Scenario: Unsupported group value
- **WHEN** a group-by value is not supported by the current API
- **THEN** the UI SHALL not send that value
- **AND** the operator SHALL see an explicit unavailable state if the page cannot support grouping
