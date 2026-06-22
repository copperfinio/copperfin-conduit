## ADDED Requirements

### Requirement: Operator admin navigation
The dashboard SHALL provide an operator-focused admin navigation structure using the donor-style left menu.

#### Scenario: Admin navigation groups render
- **WHEN** the dashboard loads
- **THEN** the left navigation SHALL include grouped admin sections for operations, configuration, observability, and diagnostics or equivalent labels

#### Scenario: Active admin page is highlighted
- **GIVEN** an operator opens an admin page
- **WHEN** the navigation renders
- **THEN** the current page SHALL be visually highlighted
- **AND** other pages SHALL remain available from the same navigation rail

#### Scenario: Donor-style rail structure is preserved
- **WHEN** the admin shell renders
- **THEN** it SHALL use a compact icon rail and grouped secondary text rail comparable to the donor dashboard
- **AND** the workspace SHALL not collapse into a narrow content strip

### Requirement: Read-only admin pages first
The dashboard SHALL provide read-only admin pages before introducing write actions.

#### Scenario: Models page renders
- **WHEN** the operator opens the Models page
- **THEN** the dashboard SHALL show configured model aliases, provider family, upstream model ID, and endpoint compatibility where available

#### Scenario: Providers page renders
- **WHEN** the operator opens the Providers page
- **THEN** the dashboard SHALL show provider auth readiness and status
- **AND** it SHALL not display tokens, API keys, or OAuth secrets

#### Scenario: Routes page renders
- **WHEN** the operator opens the Routes page
- **THEN** the dashboard SHALL show endpoint routing behavior and recent route decisions where available

#### Scenario: Settings page renders
- **WHEN** the operator opens the Settings page
- **THEN** the dashboard SHALL show effective local settings in redacted form

#### Scenario: Traffic page renders
- **WHEN** the operator opens the Traffic page
- **THEN** the dashboard SHALL show recent request volume, token volume, latency, and failure shape using the shared telemetry controls

#### Scenario: Fusion runs page renders
- **WHEN** the operator opens the Fusion runs page
- **THEN** the dashboard SHALL show Fusion parent runs and child model calls with panel and synthesizer phases

### Requirement: Duration controls only where useful
Admin pages SHALL use the shared duration dropdown only when the page displays time-windowed data.

#### Scenario: Log page uses duration
- **WHEN** the operator opens a request log or telemetry log page
- **THEN** the page SHALL use the shared duration dropdown to filter visible data

#### Scenario: Operations page uses duration
- **WHEN** the operator opens Overview, Traffic, Fusion runs, or Health
- **THEN** the shared duration dropdown SHALL filter the visible operational telemetry

#### Scenario: Static configuration page hides duration
- **WHEN** the operator opens a static configuration page such as Models or Settings
- **THEN** the duration dropdown SHALL be hidden or disabled if it does not affect the page

### Requirement: Redacted admin diagnostics
The dashboard SHALL provide diagnostics that are useful for support without leaking credentials.

#### Scenario: Diagnostics render
- **WHEN** the operator opens Diagnostics
- **THEN** the dashboard SHALL show local health checks, service status, configured endpoint roots, and recent error classes
- **AND** it SHALL redact secret-like values
