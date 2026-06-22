## ADDED Requirements

### Requirement: Fusion run visibility
The dashboard SHALL expose Fusion runs as parent operations with visible child calls for council members and synthesizer.

#### Scenario: Fusion run renders child calls
- **GIVEN** a Fusion request completes
- **WHEN** the operator opens the Fusion dashboard view
- **THEN** the view SHALL show the Fusion run
- **AND** it SHALL show council member child calls
- **AND** it SHALL show the synthesizer child call separately

### Requirement: Fusion timing and usage
Fusion observability SHALL include timing and usage fields for each Fusion child call when available.

#### Scenario: Child timing is available
- **GIVEN** Fusion child call timings were captured
- **WHEN** the operator inspects a Fusion run
- **THEN** each child call SHALL show provider, model, role, duration, status, and token usage where available

#### Scenario: Usage is unknown
- **GIVEN** a provider does not return usage for a child call
- **WHEN** the Fusion run renders
- **THEN** usage SHALL be shown as unknown
- **AND** the dashboard SHALL not fabricate zero-token usage

### Requirement: Fusion error classification
Fusion observability SHALL classify known provider and adapter failures without exposing sensitive message content.

#### Scenario: Unsupported assistant prefill
- **GIVEN** a provider rejects assistant message prefill
- **WHEN** the error is captured
- **THEN** the dashboard SHALL classify it as an assistant-prefill compatibility failure
- **AND** the raw prompt content SHALL remain redacted

#### Scenario: Provider auth failure
- **GIVEN** a provider call fails because auth is missing or expired
- **WHEN** the error is captured
- **THEN** the dashboard SHALL classify it as an auth failure
- **AND** it SHALL indicate the provider involved

