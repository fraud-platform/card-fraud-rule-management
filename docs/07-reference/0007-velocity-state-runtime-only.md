# ADR 0007: Velocity State at Runtime Only

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

Velocity rules track transaction patterns over time windows:

- "More than 5 transactions in 10 minutes by card"
- "Total amount exceeds $10,000 in 1 hour by merchant"
- "Distinct cards > 100 in 24 hours by BIN"

These require:

- **Per-transaction counter updates** (high write volume)
- **Time-window expiration** (TTL-based cleanup)
- **Low-latency reads** (sub-millisecond evaluation)
- **Atomic increments** (no lost updates)

Storage approaches considered:
- PostgreSQL (rejected: too slow, high write overhead)
- This system's database (rejected: not designed for high-frequency updates)
- Redis at runtime (selected: purpose-built for counters)

## Decision

**Velocity is DEFINED in this system but STATE is maintained only at runtime (Quarkus + Redis).**

### Separation of Concerns

| Concern | Control Plane (This System) | Runtime (Quarkus) |
|---------|---------------------------|------------------|
| **Define Velocity Fields** | ✅ Field catalog with metadata | ❌ Not involved |
| **Store Velocity Config** | ✅ RuleFieldMetadata (aggregation, window, group_by) | ❌ Not involved |
| **Update Counters** | ❌ Never | ✅ Redis INCR/EXPIRE |
| **Read Current Values** | ❌ Never | ✅ Redis GET |
| **Evaluate Rules** | ❌ Never | ✅ Compare value to threshold |

### Velocity Definition (Control Plane)

Velocity is treated as a derived `RuleField` with metadata:

```sql
-- RuleField entry for a velocity field
INSERT INTO fraud_gov.rule_fields (field_key, display_name, data_type, ...) VALUES (
    'velocity_txn_count_10m_by_card',
    'Transaction Count (10min, by Card)',
    'NUMBER',
    ...
);

-- Velocity configuration in metadata
INSERT INTO fraud_gov.rule_field_metadata (field_key, meta_key, meta_value) VALUES (
    'velocity_txn_count_10m_by_card',
    'velocity',
    '{
        "aggregation": "COUNT",
        "metric": "txn",
        "window": {"value": 10, "unit": "MINUTES"},
        "group_by": ["CARD"]
    }'::jsonb
);
```

### Velocity State (Runtime Only)

Runtime (Quarkus) manages all velocity state:

```java
// Runtime velocity update (per transaction)
public void updateVelocity(Transaction txn) {
    String key = String.format(
        "vel:COUNT:txn:10m:CARD:%s",
        txn.getCardHash()
    );

    // Atomic increment
    redis.incr(key);

    // Set expiration (10 minutes)
    redis.expire(key, 600);
}

// Runtime rule evaluation
public boolean evaluateVelocityRule(Rule rule, Transaction txn) {
    String key = buildVelocityKey(rule, txn);
    Long currentValue = redis.get(key);

    return currentValue != null &&
           currentValue > rule.getThreshold();
}
```

### Velocity Key Format (Locked)

```
vel:{aggregation}:{metric}:{window}:{grouping}:{group_value}
```

**Examples:**

```
vel:COUNT:txn:10m:CARD:a1b2c3d4e5f6
vel:SUM:amount:1h:MERCHANT:merchant_123
vel:DISTINCT:card:24h:BIN:412345
```

## Rationale

1. **Performance**
   - Redis: Sub-millisecond reads/writes
   - PostgreSQL: 1-10ms (too slow for per-transaction updates)

2. **Scalability**
   - Redis: Handles millions of updates per second
   - PostgreSQL: Would be overwhelmed by transaction volume

3. **TTL Management**
   - Redis: Built-in key expiration
   - PostgreSQL: Requires background cleanup jobs

4. **Separation of Concerns**
   - Control plane: Configuration and governance
   - Runtime: Execution and state

## Implementation

### Control Plane: Velocity Definition

```python
# Velocity field creation
POST /api/v1/rule-fields
{
    "field_key": "velocity_txn_count_10m_by_card",
    "display_name": "Transaction Count (10min, by Card)",
    "data_type": "NUMBER",
    "allowed_operators": ["GT", "GTE", "EQ", "LT", "LTE"],
    "multi_value_allowed": false,
    "is_sensitive": false,
    "is_active": true
}

# Velocity metadata configuration
PUT /api/v1/rule-fields/velocity_txn_count_10m_by_card/metadata/velocity
{
    "aggregation": "COUNT",
    "metric": "txn",
    "window": {"value": 10, "unit": "MINUTES"},
    "group_by": ["CARD"]
}
```

### Control Plane: Compiler Includes Velocity in AST

```json
{
  "rules": [
    {
      "ruleId": "...",
      "when": {
        "field": "velocity_txn_count_10m_by_card",
        "op": "GT",
        "value": 5
      },
      "action": "BLOCK"
    }
  ]
}
```

The AST tells runtime:
- Which velocity field to check
- What operator to use
- What threshold to compare against

Runtime looks up velocity configuration from its own cache.

## Consequences

### ALLOWLIST

- **Performance:** Transaction processing not bottlenecked by database
- **Scalability:** Runtime scales independently of control plane
- **Clean Separation:** Each system handles its core responsibility

### BLOCKLIST

- **Dual Configuration:** Velocity defined in control plane, used by runtime
- **Sync Required:** Runtime must know about new velocity fields
- **Debugging:** Velocity state not visible in control plane database

### Mitigations

- **Artifact Polling:** Runtime polls for new artifacts (includes velocity config)
- **Monitoring:** Runtime exports velocity metrics for observability
- **Documentation:** Clear separation documented in both systems

## Alternatives Considered

1. **PostgreSQL for Velocity State**
   - Rejected: Too slow, high write overhead
   - Would bottleneck transaction processing

2. **Control Plane Manages Velocity**
   - Rejected: Adds unnecessary complexity and latency
   - Not the core responsibility of governance system

3. **Custom Velocity Service**
   - Deferred: Could extract velocity as standalone service
   - Current approach: Embedded in runtime is sufficient

## Velocity Risk Classification

Velocity rules carry cardinality risk. The control plane validates:

| Grouping Dimension | Risk Level | Notes |
|--------------------|------------|-------|
| `BIN`, `MCC` | Low | Limited cardinality (thousands) |
| `MERCHANT` | Medium | Higher cardinality (millions) |
| `CARD` | High | Very high cardinality (billions) |
| `DEVICE_ID` | Very High | Prohibited or requires override |

**Approval-time validation:** Control plane rejects dangerous velocity definitions.

## References

- [Domain Model Documentation](../07-reference/domain-model.md)
- [Architecture Documentation](../02-development/architecture.md)
- [Compiler Documentation](../02-development/compiler.md)

## Related Decisions

- [ADR 0005: Deterministic Rule Compiler](0005-deterministic-rule-compiler.md)
- [ADR 0006: Control Plane vs Runtime Separation](0006-control-plane-runtime-separation.md)
