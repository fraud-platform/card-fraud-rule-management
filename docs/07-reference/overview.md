# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records (ADRs) for the Fraud Rule Governance API.

## What is an ADR?

An ADR documents a significant architectural decision, its context, consequences, and alternatives. ADRs provide:

- **Historical Context:** Why was this decision made?
- **Current State:** What is the current approach?
- **Trade-offs:** What were the alternatives and their pros/cons?

## ADR Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| [0001](0001-use-doppler-for-secrets-management.md) | Use Doppler for Secrets Management | Accepted | 2026-01-15 |
| [0002](0002-uuidv7-for-all-identifiers.md) | UUIDv7 for All Identifiers | Accepted | 2026-01-15 |
| [0003](0003-postgresql-jsonb-hybrid-storage.md) | PostgreSQL with JSONB Hybrid Storage | Accepted | 2026-01-15 |
| [0004](0004-maker-checker-governance.md) | Maker-Checker Governance Pattern | Accepted | 2026-01-15 |
| [0005](0005-deterministic-rule-compiler.md) | Deterministic Rule Compiler | Accepted | 2026-01-15 |
| [0006](0006-control-plane-runtime-separation.md) | Control Plane vs Runtime Separation | Accepted | 2026-01-15 |
| [0007](0007-velocity-state-runtime-only.md) | Velocity State at Runtime Only | Accepted | 2026-01-15 |

## ADR Template

When creating a new ADR, use this template:

```markdown
# ADR ####: [Title]

**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

[Describe the context and problem statement clearly.]

## Decision

[State the decision concisely.]

### Rationale

[Explain the reasoning behind the decision.]

## Implementation

[Describe how the decision is implemented.]

## Consequences

### ALLOWLIST
- [List ALLOWLIST consequences.]

### BLOCKLIST
- [List BLOCKLIST consequences.]

### Mitigations
- [Describe how BLOCKLIST consequences are mitigated.]

## Alternatives Considered

1. **[Alternative Name]**
   - Rejected: [Reason]
   - Accepted for: [Limited use case, if any]

## References

[Links to related documentation.]

## Related Decisions

- [ADR ####: [Related Decision Title](####-filename.md)
```

## How to Create an ADR

1. Copy the template above
2. Use sequential numbering (e.g., 0008, 0009)
3. Use kebab-case for filename (e.g., `0008-decision-name.md`)
4. Add entry to index in this README
5. Link related ADRs

## ADR Lifecycle

- **Proposed:** Initial draft for review
- **Accepted:** Decision approved and implemented
- **Deprecated:** Decision no longer recommended but not replaced
- **Superseded:** Decision replaced by a newer ADR (link to new ADR)

## References

- [Michael Nygard's ADR Template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- [ThoughtWorks Architecture Decision Records](https://www.thoughtworks.com/radar/techniques/practice/decision-record)
