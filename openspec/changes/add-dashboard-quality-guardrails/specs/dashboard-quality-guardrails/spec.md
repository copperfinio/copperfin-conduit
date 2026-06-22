## ADDED Requirements

### Requirement: Dashboard browser smoke verification
Dashboard changes SHALL include a repeatable browser smoke check for the primary dashboard page.

#### Scenario: Dashboard loads cleanly
- **WHEN** the browser smoke check opens `/dashboard`
- **THEN** the page SHALL render the shell and primary content
- **AND** the browser console SHALL not contain dashboard JavaScript errors

### Requirement: Dashboard telemetry tests
Telemetry data used by dashboard panels SHALL have focused tests for aggregation and empty-state behavior.

#### Scenario: Empty telemetry shape
- **GIVEN** there is no telemetry in the selected window
- **WHEN** the telemetry data shape is generated
- **THEN** it SHALL return deterministic empty structures
- **AND** the dashboard SHALL be able to render them without client-side exceptions

### Requirement: Generated artifact hygiene
Dashboard development SHALL keep generated artifacts out of commits.

#### Scenario: Generated folders exist locally
- **GIVEN** local dashboard tooling created generated folders
- **WHEN** source changes are prepared
- **THEN** generated folders such as `preview/`, `output/`, `.playwright-cli/`, `__pycache__/`, and `.pytest_cache/` SHALL not be staged

### Requirement: Documented dashboard workflow
The repository SHALL document how to run and verify dashboard work locally.

#### Scenario: New contributor verifies dashboard work
- **GIVEN** a contributor has a local checkout
- **WHEN** they read the dashboard verification docs
- **THEN** they SHALL find commands for starting the dashboard, running checks, and performing browser verification

