# ADR 0005: Deterministic Rule Compiler

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

The RuleSet compiler transforms approved rule configurations into a deterministic AST/JSON format that the runtime engine (Quarkus) can execute.

**Critical Requirements:**

1. **Determinism:** Same input must produce byte-for-byte identical output
2. **Explicit Semantics:** Evaluation mode must be declared, never inferred
3. **Validation:** All fields, operators, and types must be validated
4. **Runtime Contract:** Output schema must match runtime expectations exactly

Compiler approaches considered:
- String concatenation (rejected: unsafe, non-deterministic)
- Code generation (rejected: too complex, hard to audit)
- JSON AST generation (selected: safe, auditable, deterministic)

## Decision

**Implement a deterministic compiler that generates validated JSON AST with explicit evaluation semantics.**

### Core Principles

1. **Deterministic Output**
   - Rules sorted by `(priority DESC, rule_id ASC)`
   - JSON keys sorted alphabetically at all levels
   - No timestamps or random values in output

2. **Explicit Evaluation Mode**
   - `FIRST_MATCH` for ALLOWLIST, BLOCKLIST, AUTH
   - `ALL_MATCHING` for MONITORING
   - Always declared in AST, never inferred from RuleType

3. **Comprehensive Validation**
   - All field references must exist in RuleField catalog
   - Operators must be in field's `allowed_operators`
   - Data types must match field's `data_type`
   - Compiler fails before writing `compiled_ast`

## Implementation

### Compilation Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Load RuleSet                                         │
│   - Verify: status IN (APPROVED, ACTIVE)                    │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Load Attached RuleVersions                          │
│   - Via ruleset_rules junction table                        │
│   - Verify: ALL(status = APPROVED)                          │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Load Rule Field Catalog                              │
│   - Only active fields (is_active = true)                   │
│   - Build: field_key → metadata lookup                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: Validate Condition Trees                             │
│   FOR EACH rule_version:                                     │
│     - validate_condition_tree(rv.condition_tree)             │
│     - Check: fields exist, ops allowed, types match          │
│   ON ERROR: Raise CompilationError with context              │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 5: Sort Rules Deterministically                         │
│   - Load Rule entities (for stable rule_id)                  │
│   - Sort: ORDER BY priority DESC, rule_id ASC               │
│   - Result: List[(RuleVersion, Rule)]                       │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 6: Map RuleType to Evaluation Mode                      │
│   - ALLOWLIST  → FIRST_MATCH                                 │
│   - BLOCKLIST  → FIRST_MATCH                                 │
│   - AUTH   → FIRST_MATCH                                 │
│   - MONITORING  → ALL_MATCHING                                │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 7: Build AST Structure                                  │
│   - Create dict with ruleset metadata                        │
│   - Add rules array with sorted rule data                    │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 8: Canonicalize JSON                                   │
│   - Sort all dict keys alphabetically                        │
│   - Recursively process nested structures                    │
│   - Preserve array order (already sorted)                    │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
                      Compiled AST (dict)
```

### Output Schema (AST)

```json
{
  "rulesetId": "01918052-461f-74e3-8000-000000000001",
  "version": 7,
  "ruleType": "MONITORING",
  "evaluation": {
    "mode": "ALL_MATCHING"
  },
  "velocityFailurePolicy": "SKIP",
  "compiledAt": "2026-01-15T10:30:00Z",
  "rules": [
    {
      "ruleId": "01918052-1234-5678-9000-000000000001",
      "priority": 100,
      "name": "High amount velocity check",
      "when": {
        "and": [
          { "field": "amount", "op": "GT", "value": 3000 },
          { "field": "velocity_txn_count_5m_by_card", "op": "GT", "value": 5 }
        ]
      },
      "action": "FLAG",
      "scope": {
        "network": ["VISA"],
        "country": ["IN"]
      }
    }
  ]
}
```

### Rule Type to Evaluation Mode Mapping (LOCKED)

| RuleType | Evaluation Mode | Description |
|----------|----------------|-------------|
| `ALLOWLIST` | `FIRST_MATCH` | Allow-list: first match wins |
| `BLOCKLIST` | `FIRST_MATCH` | Block-list: first match wins |
| `AUTH` | `FIRST_MATCH` | Real-time: fast decision |
| `MONITORING` | `ALL_MATCHING` | Analytics: collect all matches |

**Important:** This mapping is locked. Never change without coordinating with runtime.

### Validation Rules

```python
def validate_condition_tree(
    condition: dict,
    field_catalog: dict[str, RuleField],
) -> None:
    """Validate a condition tree against the field catalog."""

    if "and" in condition:
        for child in condition["and"]:
            validate_condition_tree(child, field_catalog)

    elif "or" in condition:
        for child in condition["or"]:
            validate_condition_tree(child, field_catalog)

    elif "not" in condition:
        validate_condition_tree(condition["not"], field_catalog)

    elif "field" in condition:
        # Leaf predicate
        field_key = condition["field"]
        operator = condition["op"]
        value = condition["value"]

        # Field must exist and be active
        if field_key not in field_catalog:
            raise CompilationError(f"Unknown field: {field_key}")
        if not field_catalog[field_key].is_active:
            raise CompilationError(f"Inactive field: {field_key}")

        # Operator must be allowed
        field = field_catalog[field_key]
        if operator not in field.allowed_operators:
            raise CompilationError(
                f"Operator {operator} not allowed for field {field_key}"
            )

        # Type validation
        validate_value_type(value, field.data_type, operator)
```

### Canonicalization

```python
def canonicalize_json(obj: Any) -> Any:
    """Recursively sort dict keys for deterministic JSON."""
    if isinstance(obj, dict):
        return {k: canonicalize_json(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [canonicalize_json(item) for item in obj]
    else:
        return obj
```

## Consequences

### ALLOWLIST

- **Determinism:** Same input → byte-for-byte identical output
- **Auditability:** AST changes reflect only semantic changes
- **Testing:** Easy to verify compiler correctness
- **Caching:** Content-addressable caching by hash

### BLOCKLIST

- **Complexity:** Compiler must be carefully maintained
- **Versioning:** AST schema changes require runtime coordination
- **Validation:** Comprehensive validation adds overhead

### Mitigations

- Comprehensive unit tests for compiler
- Schema versioning in AST for evolution
- Clear documentation of runtime contract

## Alternatives Considered

1. **String Concatenation**
   - Rejected: SQL injection risk, non-deterministic, hard to audit

2. **Code Generation (Python/Java source)**
   - Rejected: Too complex, hard to validate, security risk

3. **Schema-First (Protobuf/Thrift)**
   - Deferred: Could be adopted for performance optimization
   - Current approach: JSON is human-readable and auditable

## References

- [Compiler Documentation](../02-development/compiler.md)
- [Architecture Documentation](../02-development/architecture.md)
- [Implementation Guide](../03-api/reference.md)

## Related Decisions

- [ADR 0004: Maker-Checker Governance Pattern](0004-maker-checker-governance.md)
- [ADR 0006: Control Plane vs Runtime Separation](0006-control-plane-runtime-separation.md)
