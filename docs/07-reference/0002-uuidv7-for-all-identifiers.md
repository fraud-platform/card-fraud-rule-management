# ADR 0002: UUIDv7 for All Identifiers

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

The system requires unique identifiers for multiple entities:

- `rule_id`
- `rule_version_id`
- `ruleset_id`
- `ruleset_version_id`
- `approval_id`
- `audit_id`

Previous identifier approaches considered:
- Auto-increment integers (sequence-based)
- UUID v4 (random)
- UUID v7 (time-ordered)

## Decision

**Use UUIDv7 for all entity identifiers, generated in the application layer.**

### Rationale

1. **Time-Ordered for Performance**
   - UUIDv7 embeds timestamp in the high bits
   - B-tree index locality (nearby IDs are stored together)
   - Reduced write amplification and page churn

2. **Globally Unique**
   - No distributed coordination required
   - Safe for multi-region deployment
   - No database dependency for ID generation

3. **Security**
   - Non-guessable (prevents enumeration attacks)
   - No information leakage about record counts
   - Safer than sequential integers for user-facing IDs

4. **Auditability**
   - Timestamp embedded in ID helps with debugging
   - Can extract creation time from ID without DB lookup
   - Useful for distributed tracing

## Implementation

### UUIDv7 Format

```
UUIDv7: 01918052-461f-74e3-8000-000000000001
       └─────┬───┘└─┬─┘└─────┬────┘└────────┬──────┘
         │      │     │          │           │
         │      │     │          │           └─ Random (74 bits)
         │      │     │          └─ Version + Variant (4 bits)
         │      │     └─ Milliseconds since Unix Epoch (48 bits)
         │      └─ Sequence (12 bits)
         └─ Version (4 bits) = 0x7
```

### Application-Layer Generation

```python
# In app/domain/uuid_utils.py
from uuid import UUID, uuid7

def generate_rule_id() -> UUID:
    """Generate a new rule identifier (UUIDv7)."""
    return uuid7()

def generate_audit_id() -> UUID:
    """Generate a new audit log identifier (UUIDv7)."""
    return uuid7()
```

### Database Schema

```sql
-- All entities use PostgreSQL native UUID type
CREATE TABLE fraud_gov.rules (
    rule_id UUID PRIMARY KEY,  -- NOT gen_random_uuid()
    rule_name TEXT NOT NULL,
    -- ...
);
```

**Important:** Do NOT use `DEFAULT gen_random_uuid()` in DDL.
IDs are generated in Python code and passed to database.

## Consequences

### ALLOWLIST

- **Performance:** Better B-tree index locality than UUIDv4
- **Scalability:** No coordination for ID generation
- **Security:** Non-guessable identifiers
- **Debugging:** Timestamp embedded for troubleshooting

### BLOCKLIST

- **App Dependency:** All inserts must go through application layer
- **Direct SQL:** Manual SQL inserts need UUID generation
- **String Length:** 36 characters (vs integers)

### Mitigations

- Database triggers can use `gen_random_uuid()` for bulk operations
- Provide SQL scripts with proper UUID generation for one-off operations
- Use PostgreSQL UUID type (not string) for storage efficiency

## Alternatives Considered

1. **Auto-increment Integers**
   - Rejected: Not globally unique, exposes record counts
   - Accepted for: Internal sequence numbers (version integers)

2. **UUIDv4 (Random)**
   - Rejected: Poor B-tree locality (random distribution)
   - Considered for: Non-indexed identifiers

3. **Snowflake / Twitter IDs**
   - Rejected: Custom implementation complexity
   - Similar benefits to UUIDv7

## Performance Comparison

| Identifier Type | Index Locality | Coordination | Security | Timestamp |
|-----------------|----------------|--------------|----------|-----------|
| Auto-increment  | Excellent      | Centralized  | Poor     | No        |
| UUIDv4          | Poor           | None         | Good     | No        |
| UUIDv7          | Good           | None         | Good     | Yes       |

## References

- [UUID v7 RFC Draft](https://datatracker.ietf.org/doc/html/draft-ietf-uuidrev-rfc4122bis)
- [PostgreSQL UUID Type](https://www.postgresql.org/docs/current/datatype-uuid.html)
- [Why UUIDv7](https://www.brandur.org/uuid)

## Related Decisions

- [ADR 0001: Use Doppler for Secrets Management](0001-use-doppler-for-secrets-management.md)
- [ADR 0003: PostgreSQL with JSONB Hybrid Storage](0003-postgresql-jsonb-hybrid-storage.md)
