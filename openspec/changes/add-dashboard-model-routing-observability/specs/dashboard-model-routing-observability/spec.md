## ADDED Requirements

### Requirement: Model alias visibility
The dashboard SHALL show configured model aliases and their provider family without exposing credentials.

#### Scenario: Model aliases render
- **GIVEN** model aliases are configured
- **WHEN** the operator opens the model routing view
- **THEN** the dashboard SHALL list aliases, provider family, upstream model, and supported endpoint style where available

### Requirement: Provider auth readiness
The dashboard SHALL show provider auth readiness without displaying token values or secrets.

#### Scenario: Provider is authenticated
- **GIVEN** a provider has valid local auth state
- **WHEN** the readiness panel renders
- **THEN** the provider SHALL be marked ready
- **AND** token values SHALL not be displayed

#### Scenario: Provider auth is missing
- **GIVEN** a provider lacks required local auth state
- **WHEN** the readiness panel renders
- **THEN** the provider SHALL be marked missing or unauthenticated
- **AND** the dashboard SHALL identify the provider family involved

### Requirement: Route decision visibility
The dashboard SHALL show recent routing decisions for proxy requests.

#### Scenario: Request is routed
- **GIVEN** a client sends a request through Conduit
- **WHEN** the route decision is recorded
- **THEN** the dashboard SHALL show endpoint, requested model, selected provider, normalized model, and outcome

