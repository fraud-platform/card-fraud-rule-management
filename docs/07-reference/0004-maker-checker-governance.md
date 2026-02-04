# ADR 0004: Maker-Checker Governance Pattern

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders**: Development Team

## Context

Fraud rules control financial transactions. Errors or malicious changes can:

- Block legitimate transactions (revenue loss)
- Allow fraudulent transactions (financial loss)
- Violate regulatory requirements (compliance risk)

The system requires strong governance to prevent:

- Self-approval of changes (conflict of interest)
- Unaudited changes to production rules
- Insufficient review of high-impact changes

Governance approaches considered:
- No approval (direct deploy) - too risky
- Role-based approval (any admin can approve) - insufficient
- Maker-checker with enforced separation - selected

## Decision

**Implement strict maker-checker governance with enforced separation of duties.**

### Core Principles

1. **Maker ≠ Checker**
   - The user who creates/changes a rule cannot approve it
   - Enforced at API, repository, and database layers
   - Audit trail captures all transition attempts

2. **Immutability of Approved Entities**
   - Approved rule versions cannot be modified
   - Changes create new versions (never in-place updates)
   - All state transitions are append-only

3. **Explicit State Machine**
   - Clear states: DRAFT → PENDING_APPROVAL → APPROVED/REJECTED
   - Valid transitions enforced by code
   - State changes always create audit entries

## Implementation

### Entity State Machine

```
┌─────────────┐     submit      ┌──────────────────┐     approve/reject
│    DRAFT    │ ────────────────► │ PENDING_APPROVAL │ ─────────────────►┐
└─────────────┘                   └──────────────────┘                    │
       ▲                                  ▲                              │
       │                                  │                              │
       └──────────────────────────────────────────────────────────────────┘
                            create new version
```

### State Definitions

| State | Description | Editable | Can Transition To |
|-------|-------------|----------|-------------------|
| `DRAFT` | Initial state, being edited | Yes | PENDING_APPROVAL |
| `PENDING_APPROVAL` | Submitted for review | No | APPROVED, REJECTED |
| `APPROVED` | Approved by checker | No | SUPERSEDED (when new version approved) |
| `REJECTED` | Rejected by checker | No | - (terminal) |
| `SUPERSEDED` | Replaced by newer version | No | - (terminal) |

### API Endpoints

```python
# Maker operations
POST   /api/v1/rules                         # Create (initial DRAFT)
POST   /api/v1/rules/{id}/versions            # Create new version
POST   /api/v1/rule-versions/{id}/submit      # Submit for approval

# Checker operations
POST   /api/v1/rule-versions/{id}/approve     # Approve (maker != checker required)
POST   /api/v1/rule-versions/{id}/reject      # Reject (maker != checker required)

# Admin operations
POST   /api/v1/rulesets/{id}/activate         # Deploy to production (ADMIN only)
```

### Enforcement Layers

#### 1. API Layer (User-Facing Errors)

```python
@router.post("/rule-versions/{id}/approve")
def approve_rule_version(
    rule_version_id: str,
    payload: RuleVersionApproveRequest,
    db: DbSession,
    user: CurrentUser,
):
    """Approve a rule version (enforces maker != checker)."""
    # Get the version
    version = get_rule_version(db, rule_version_id)

    # Validate: maker != checker
    if version.created_by == get_user_id(user):
        raise HTTPException(
            status_code=403,
            detail="Cannot approve own submission. Maker cannot be checker.",
        )

    # Proceed with approval...
```

#### 2. Repository Layer (Data Integrity)

```python
def approve_rule_version(
    db: Session,
    rule_version_id: str,
    checker: str,
    remarks: str | None = None,
) -> RuleVersion:
    """Approve a rule version with state validation."""
    version = get_rule_version(db, rule_version_id)

    # State validation
    if version.status != "PENDING_APPROVAL":
        raise InvalidStateError(
            f"Cannot approve version in {version.status} state"
        )

    # Maker != checker validation
    if version.created_by == checker:
        raise MakerCheckerViolationError("Maker cannot be checker")

    # Update status atomically
    version.status = "APPROVED"
    version.approved_by = checker
    version.approved_at = datetime.now(UTC)

    return version
```

#### 3. Audit Trail (Complete History)

```sql
CREATE TABLE fraud_gov.approvals (
    approval_id   UUID PRIMARY KEY,
    entity_type   TEXT NOT NULL,      -- 'rule_version' | 'ruleset_version'
    entity_id     UUID NOT NULL,
    action        TEXT NOT NULL,      -- 'SUBMIT' | 'APPROVE' | 'REJECT'
    maker         TEXT NOT NULL,
    checker       TEXT,
    status        TEXT NOT NULL,      -- 'PENDING' | 'APPROVED' | 'REJECTED'
    remarks       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at    TIMESTAMPTZ
);
```

### Approval Response

```json
{
  "approval_id": "01918052-461f-74e3-8000-000000000001",
  "entity_type": "rule_version",
  "entity_id": "01918052-1234-5678-9000-000000000001",
  "action": "APPROVE",
  "maker": "user@example.com",
  "checker": "approver@example.com",
  "status": "APPROVED",
  "remarks": "Reviewed velocity thresholds - approved for production",
  "created_at": "2026-01-15T10:30:00Z",
  "decided_at": "2026-01-15T14:22:00Z"
}
```

## Consequences

### ALLOWLIST

- **Risk Reduction:** No single person can deploy unchecked changes
- **Audit Trail:** Complete history of who did what and when
- **Compliance:** Meets regulatory requirements for separation of duties
- **Accountability:** Clear maker and checker for each change

### BLOCKLIST

- **Throughput:** Requires two people for each change
- **Latency:** Changes cannot be deployed instantly
- **Coordination:** Multiple roles required for operations

### Mitigations

- **Emergency Approval:** Break-glass procedure with enhanced audit
- **Role Flexibility:** Users can have both MAKER and CHECKER roles
- **Bulk Operations:** Batch approval for related changes

## Alternatives Considered

1. **No Governance**
   - Rejected: Too risky for financial transactions
   - Unacceptable to regulators

2. **Self-Approval After Timeout**
   - Rejected: Defeats the purpose of separation of duties
   - Considered for: Low-risk field metadata changes only

3. **Multi-Person Approval**
   - Deferred: Requires N-of-M approval infrastructure
   - Could be added as enhancement for high-risk changes

## Roles and Permissions

| Role | Can Create | Can Submit | Can Approve | Can Reject | Can Deploy |
|------|-----------|------------|-------------|------------|------------|
| MAKER | ✅ | ✅ | ❌ | ❌ | ❌ |
| CHECKER | ✅ | ✅ | ✅ | ✅ | ❌ |
| ADMIN | ✅ | ✅ | ✅ | ✅ | ✅ |

**Key Constraint:** A user cannot approve their own submission, regardless of role.

## References

- [API Reference](../03-api/reference.md)
- [Architecture Documentation](../02-development/architecture.md)
- [Implementation Guide](../03-api/reference.md)

## Related Decisions

- [ADR 0003: PostgreSQL with JSONB Hybrid Storage](0003-postgresql-jsonb-hybrid-storage.md)
- [ADR 0005: Deterministic Rule Compiler](0005-deterministic-rule-compiler.md)
