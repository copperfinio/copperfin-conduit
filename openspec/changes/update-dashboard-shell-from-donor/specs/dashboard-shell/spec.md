## ADDED Requirements

### Requirement: Donor-aligned dashboard shell
The dashboard SHALL render a donor-aligned operational shell using a fixed icon rail, a secondary navigation rail, a compact topbar, and a full-width workspace.

#### Scenario: Desktop shell uses the full viewport
- **GIVEN** the dashboard is opened on a desktop viewport
- **WHEN** the page loads
- **THEN** the icon rail SHALL remain fixed on the left
- **AND** the secondary navigation rail SHALL render next to it
- **AND** the workspace SHALL consume the remaining horizontal space without collapsing into a narrow strip

#### Scenario: Shell remains stable while scrolling
- **GIVEN** dashboard content exceeds the viewport height
- **WHEN** the operator scrolls the workspace
- **THEN** the rails SHALL remain visually stable
- **AND** the content SHALL scroll without horizontal overflow

### Requirement: Donor-style left navigation
The dashboard SHALL provide a left-side menu comparable to the donor dashboard, with a compact icon rail and a grouped text navigation rail.

#### Scenario: Navigation groups render
- **WHEN** the dashboard shell renders
- **THEN** the secondary navigation rail SHALL group links into operator-friendly sections
- **AND** those sections SHALL include operations, configuration, observability, and diagnostics or equivalent labels

#### Scenario: Active section is visible
- **GIVEN** an operator opens a dashboard page
- **WHEN** the left navigation renders
- **THEN** the active page SHALL be visually highlighted in the navigation
- **AND** inactive pages SHALL remain readable without dominating the content

### Requirement: Donor visual tokens
The dashboard SHALL use a shared visual token set derived from the donor dashboard for backgrounds, panels, borders, text, status colors, and accent colors.

#### Scenario: Panels share consistent chrome
- **WHEN** metric cards, tables, and graph panels render
- **THEN** they SHALL use the same panel background, border radius, border weight, and typography scale
- **AND** accent colors SHALL match the dashboard token vocabulary

### Requirement: Safe empty and offline states
The dashboard SHALL render valid content when telemetry is empty, unavailable, or partially missing.

#### Scenario: Telemetry is unavailable
- **GIVEN** the telemetry endpoint fails or returns no useful data
- **WHEN** the dashboard renders
- **THEN** the shell SHALL remain intact
- **AND** panels SHALL show an explicit offline or empty state instead of throwing JavaScript errors

### Requirement: No accidental full-page JavaScript failure
Dashboard client code SHALL guard optional DOM writes so a missing element cannot blank or break the page.

#### Scenario: Optional panel is absent
- **GIVEN** a page does not include an optional panel target
- **WHEN** dashboard JavaScript runs
- **THEN** the script SHALL skip that target safely
- **AND** other dashboard panels SHALL continue to update
