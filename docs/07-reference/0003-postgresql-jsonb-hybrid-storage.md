# ADR 0003: PostgreSQL with JSONB Hybrid Storage

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

The system must store:

- **Structured metadata**: RuleField definitions, user information
- **Hierarchical data**: Rule condition trees (AND/OR/NOT logic)
- **Governance state**: Status transitions, approval workflows
- **Audit trail**: Complete history of all changes

Storage approaches considered:
- Relational only (many tables, frequent schema changes)
- Document store (MongoDB - weak governance support)
- Hybrid PostgreSQL (relational + JSONB)

## Decision

**Use PostgreSQL with a hybrid storage model: Relational for governance, JSONB for flexibility.**

### Storage Strategy

| Concern | Storage | Rationale |
|---------|---------|-----------|
| Entity identity | Relational columns | Queryable, indexed, foreign keys |
| Lifecycle state | Relational columns | Status transitions, constraints |
| Maker-checker | Relational tables | Governance workflows |
| Rule conditions | JSONB | Flexible, hierarchical expressions |
| Field metadata | JSONB | Extension without schema churn |
| Audit trail | Relational + JSONB | Queryable with JSON diffs |

## Rationale

1. **Governance Requirements**
   - Strong ACID guarantees for state transitions
   - Foreign key constraints prevent orphaned records
   - Row-Level Security (RLS) for multi-tenant isolation
   - Familiar to regulators and auditors

2. **Schema Flexibility**
   - Rule conditions are hierarchical trees (JSONB natural fit)
   - Field metadata is extensible (no schema churn)
   - Velocity parameters are complex (aggregation, window, grouping)

3. **Performance**
   - JSONB with GIN indexes for efficient querying
   - Relational indexes for filtered queries (status, type, dates)
   - Connection pooling for high concurrency

4. **Operational Maturity**
   - PostgreSQL is well-understood operationally
   - Neon provides branching for test environments
   - Mature tooling for backups, monitoring, replication

## Implementation

### Core Tables

#### Entity Tables (Relational)

```sql
CREATE TABLE fraud_gov.rules (
    rule_id         UUID PRIMARY KEY,
    rule_name       TEXT NOT NULL,
    rule_type       TEXT NOT NULL,
    current_version INTEGER NOT NULL,
    status          TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rules_status ON fraud_gov.rules(status, rule_type);
```

#### Version Tables (Relational + JSONB)

```sql
CREATE TABLE fraud_gov.rule_versions (
    rule_version_id UUID PRIMARY KEY,
    rule_id         UUID REFERENCES fraud_gov.rules(rule_id),
    version         INTEGER NOT NULL,
    condition_tree  JSONB NOT NULL,  -- Hierarchical rule logic
    priority        INTEGER NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    status          TEXT NOT NULL,
    UNIQUE (rule_id, version)
);
```

#### Condition Tree Example (JSONB)

```json
{
  "and": [
    { "field": "mcc", "op": "IN", "value": ["5967", "7995"] },
    { "field": "amount", "op": "GT", "value": 3000 },
    {
      "or": [
        { "field": "velocity_txn_count_5m_by_card", "op": "GT", "value": 5 },
        { "field": "velocity_distinct_merchants_24h_by_card", "op": "GT", "value": 3 }
      ]
    }
  ]
}
```

#### Metadata Tables (JSONB for extensibility)

```sql
CREATE TABLE fraud_gov.rule_field_metadata (
    field_key   TEXT REFERENCES fraud_gov.rule_fields(field_key),
    meta_key    TEXT NOT NULL,
    meta_value  JSONB NOT NULL,  -- Extensible metadata
    PRIMARY KEY (field_key, meta_key)
);
```

#### Metadata Value Example

```json
{
  "velocity": {
    "aggregation": "COUNT",
    "metric": "txn",
    "window": {"value": 10, "unit": "MINUTES"},
    "group_by": ["CARD"]
  },
  "ui": {
    "group": "Velocity",
    "order": 100,
    "icon": "clock-circle"
  }
}
```

### JSONB Indexing Strategy

```sql
-- GIN index for condition tree queries
CREATE INDEX idx_rule_versions_condition_gin
    ON fraud_gov.rule_versions USING GIN (condition_tree);

-- Partial index for approved versions only
CREATE INDEX idx_rule_versions_approved
    ON fraud_gov.rule_versions(rule_id, version)
    WHERE status = 'APPROVED';
```

## Consequences

### ALLOWLIST

- **Governance:** Strong ACID, constraints, and auditability
- **Flexibility:** JSONB allows schema evolution without DDL
- **Performance:** Targeted indexes for common query patterns
- **Compliance:** PostgreSQL is familiar to auditors

### BLOCKLIST

- **Complexity:** Need to understand when to use relational vs JSONB
- **Query Complexity:** Some queries need JSON operators (`->>`, `@>`)
- **Storage:** JSONB has overhead vs pure relational

### Mitigations

- Clear documentation of storage strategy per entity type
- Repository layer encapsulates JSONB query complexity
- Regular index usage reviews

## Alternatives Considered

1. **Pure Relational (no JSONB)**
   - Rejected: Schema churn for field metadata, velocity parameters
   - Complexity: Many-to-many tables for condition tree nodes

2. **MongoDB**
   - Rejected: Weak governance support (no ACID across collections)
   - Rejected: Not familiar to regulators
   - Accepted for: High-cardinality analytics (not this system)

3. **Hybrid (PostgreSQL + MongoDB)**
   - Rejected: Operational complexity of two databases
   - Rejected: Transaction boundaries across systems

## Data Model Principles

1. **Rules are data, not code**
   - Store structured configuration objects
   - Never concatenate logic strings
   - Never parse dynamic SQL

2. **Separation of concerns**
   - Relational: Identity, lifecycle, governance
   - JSONB: Hierarchical data, extensible metadata

3. **Schema evolution**
   - Add columns for cross-cutting concerns
   - Use JSONB for domain-specific extensions
   - Version the AST schema for runtime compatibility

## References

- [PostgreSQL JSONB Documentation](https://www.postgresql.org/docs/current/datatype-json.html)
- [JSONB Indexing Strategies](https://www.postgresql.org/docs/current/indexes-types.html#INDEXES-TYPES-GIN)
- [Architecture Documentation](../02-development/architecture.md)

## Related Decisions

- [ADR 0002: UUIDv7 for All Identifiers](0002-uuidv7-for-all-identifiers.md)
- [ADR 0004: Maker-Checker Governance Pattern](0004-maker-checker-governance.md)
