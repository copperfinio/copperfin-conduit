# OpenSpec Instructions

Instructions for AI coding assistants using OpenSpec in Copperfin Conduit.

## Quick Checklist

- Search existing work: `openspec list`, `openspec list --specs`, and focused `rg` searches.
- Pick a unique verb-led `change-id` in kebab case, such as `update-dashboard-shell-from-donor`.
- Scaffold `proposal.md`, `tasks.md`, optional `design.md`, and delta specs under `openspec/changes/<change-id>/specs/<capability>/spec.md`.
- Write deltas with `## ADDED|MODIFIED|REMOVED Requirements`.
- Every requirement MUST include at least one `#### Scenario:` block.
- Validate with `openspec validate <change-id> --strict`.
- Do not implement a proposed change until the proposal is approved.

## When To Create A Change

Create an OpenSpec change for:

- New dashboard surfaces or major page rewrites.
- New telemetry APIs, data contracts, or storage behavior.
- Changes to request shaping, provider routing, Fusion orchestration, or auth behavior.
- Architecture, security, logging, or observability changes.

Small bug fixes, typo fixes, and restoration of already-specified behavior can be handled directly.

## Directory Structure

```text
openspec/
  project.md
  AGENTS.md
  specs/
  changes/
    <change-id>/
      proposal.md
      tasks.md
      design.md
      specs/
        <capability>/
          spec.md
```

## Spec Format

Use this format for deltas:

```markdown
## ADDED Requirements

### Requirement: Capability name
The system SHALL do the thing.

#### Scenario: Success case
- **WHEN** the user performs an action
- **THEN** the expected result occurs
```

Requirements use SHALL or MUST for normative behavior. Use SHOULD only for intentional guidance.

## Implementation Gate

When implementing an approved change:

1. Read `proposal.md`.
2. Read `design.md` if present.
3. Read `tasks.md`.
4. Implement tasks sequentially.
5. Update task checkboxes only after the work is actually complete.
6. Run targeted tests and browser verification when UI is touched.

