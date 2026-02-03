# Fraud Rule Compiler Module

## Overview

The compiler module is the **CORE VALUE** of the Fraud Rule Governance API. It transforms approved RuleSets from the governance database into deterministic AST/JSON that the Quarkus runtime engine can execute.

## Key Principles

### 1. Determinism
**Requirement**: Same input produces byte-for-byte identical output.

**Implementation**:
- Rules sorted by `(priority DESC, rule_id ASC)`
- JSON keys sorted alphabetically at all levels
- No timestamps or random values in output
- Canonical JSON serialization

**Why it matters**:
- Enables hash-based change detection
- Simplifies audit trails (only semantic changes show diffs)
- Supports content-addressable caching

### 2. Validation First
All references are validated before compilation:
- Field existence and active status
- Operator allowance for each field
- Value type matching
- Multi-value constraints

**Fail fast**: Invalid rules are rejected at compile-time, not runtime.

### 3. Explicit Semantics
Evaluation modes and policies are declared, never inferred:
- `ALLOWLIST` → `FIRST_MATCH`
- `BLOCKLIST` → `FIRST_MATCH`
- `AUTH` → `FIRST_MATCH`
- `MONITORING` → `ALL_MATCHING`

These mappings are **locked** and part of the contract with runtime.

## Module Structure

```
app/compiler/
├── __init__.py          # Package exports
├── canonicalizer.py     # JSON canonicalization
├── validator.py         # Condition tree validation
├── compiler.py          # Main compilation logic
└── README.md           # This file
```

## Components

### canonicalizer.py

**Purpose**: Ensure deterministic JSON output

**Functions**:
- `canonicalize_json(obj)` - Recursively sort dict keys
- `to_canonical_json_string(obj)` - Compact canonical JSON
- `to_canonical_json_pretty(obj)` - Pretty-printed canonical JSON

**Usage**:
```python
from app.compiler.canonicalizer import canonicalize_json

data = {"z": 1, "a": {"c": 2, "b": 3}}
canonical = canonicalize_json(data)
# Result: {"a": {"b": 3, "c": 2}, "z": 1}
```

**Note**: Arrays preserve their input order. Sort arrays BEFORE canonicalization if order matters.

### validator.py

**Purpose**: Validate condition tree structure and semantics

**Functions**:
- `validate_condition_tree(condition_tree, rule_fields, allow_unknown_fields=False)` - Main validation

**Validates**:
1. Tree structure (and/or/not/field)
2. Field existence and active status
3. Operator allowance
4. Value type matching
5. Multi-value constraints

**Condition Tree Formats**:
The validator supports **both** lowercase key format and type-based format:

**Format 1: Lowercase keys (original)**
```json
{
  "and": [
    {"field": "amount", "op": "GT", "value": 1000},
    {"field": "currency", "op": "IN", "value": ["USD", "EUR"]}
  ]
}
```

**Format 2: Type-based with explicit type field**
```json
{
  "type": "AND",
  "conditions": [
    {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 1000},
    {"type": "CONDITION", "field": "currency", "operator": "IN", "value": ["USD", "EUR"]}
  ]
}
```

**Error Handling**: Raises `ValidationError` with detailed context including JSONPath.

**Usage**:
```python
from app.compiler.validator import validate_condition_tree

rule_fields = {
    "mcc": {
        "data_type": "STRING",
        "allowed_operators": ["EQ", "IN"],
        "multi_value_allowed": True,
        "is_active": True
    }
}

tree = {"field": "mcc", "op": "IN", "value": ["5967"]}
validate_condition_tree(tree, rule_fields)  # Passes

bad_tree = {"field": "mcc", "op": "GT", "value": 5}
validate_condition_tree(bad_tree, rule_fields)  # Raises ValidationError
```

### compiler.py

**Purpose**: Main compilation orchestration

**Main Function**:
```python
compile_ruleset(ruleset_id: UUID, db: Session) -> dict
```

**Compilation Pipeline**:
1. Load RuleSet from database
2. Verify RuleSet is APPROVED
3. Load all attached RuleVersions
4. Verify all RuleVersions are APPROVED
5. Load rule field catalog
6. Validate all condition trees
7. Sort rules deterministically
8. Map rule_type to evaluation mode
9. Build AST structure
10. Canonicalize JSON

**Output Format**:
```json
{
  "rulesetId": "rs-uuid",
  "version": 7,
  "ruleType": "MONITORING",
  "evaluation": {
    "mode": "ALL_MATCHING"
  },
  "velocityFailurePolicy": "SKIP",
  "rules": [
    {
      "ruleId": "rule-uuid",
      "ruleVersionId": "version-uuid",
      "priority": 100,
      "when": {
        "and": [
          {"field": "amount", "op": "GT", "value": 3000}
        ]
      },
      "action": "FLAG"
    }
  ]
}
```

## Error Handling

### ValidationError
**Raised when**: Condition tree validation fails

**Details include**:
- JSONPath to problematic node
- Field key
- Expected vs actual values
- Allowed operators

**Example**:
```python
ValidationError(
    "Operator 'GT' not allowed for field 'mcc' at $.and[0]",
    details={
        "path": "$.and[0]",
        "field_key": "mcc",
        "operator": "GT",
        "allowed_operators": ["EQ", "IN", "NOT_IN"]
    }
)
```

### CompilationError
**Raised when**: Overall compilation fails

**Details include**:
- RuleSet ID
- Failing rule version ID
- Underlying error
- Condition tree (for debugging)

**Example**:
```python
CompilationError(
    "Condition tree validation failed for rule version abc-123",
    details={
        "ruleset_id": "rs-456",
        "rule_version_id": "abc-123",
        "rule_id": "r-10",
        "error": "Unknown field 'nonexistent'",
        "condition_tree": {...}
    }
)
```

### ConflictError
**Raised when**: RuleSet is not APPROVED

**Example**:
```python
ConflictError(
    "RuleSet must be APPROVED or ACTIVE to compile (status: DRAFT)",
    details={
        "ruleset_id": "rs-456",
        "status": "DRAFT"
    }
)
```

## Testing

Run compiler tests:
```bash
uv run pytest tests/test_compiler.py -v
```

### Test Coverage

**Canonicalizer**:
- Key sorting (simple and nested)
- List order preservation
- Determinism (same input = same output)
- Pretty printing

**Validator**:
- Valid conditions (simple, AND, OR, NOT, nested)
- Invalid structure
- Unknown fields
- Inactive fields
- Disallowed operators
- Type mismatches
- Multi-value constraints
- BETWEEN operator

**Compiler**:
- Evaluation mode mapping
- Action mapping
- Locked semantics verification

## Integration with Repository Layer

The compiler is called from `app/repos/ruleset_repo.py`:

```python
from app.compiler.compiler import compile_ruleset as compile_ruleset_ast

def compile_ruleset(db: Session, *, ruleset_id: Any, invoked_by: str) -> dict:
    """Compile RuleSet and store AST in database."""
    compiled_ast = compile_ruleset_ast(ruleset_id, db)
    ruleset.compiled_ast = compiled_ast
    db.flush()
    # ... audit and notify
    return {"ruleset_id": str(ruleset_id), "compiled_ast": compiled_ast}
```

## API Endpoints

### Compile RuleSet
```http
POST /api/v1/rulesets/{ruleset_id}/compile
```

**Authorization**: Requires ADMIN or CHECKER role

**Response**:
```json
{
  "ruleset_id": "rs-uuid",
  "compiled_ast": {
    "rulesetId": "rs-uuid",
    "version": 7,
    "ruleType": "MONITORING",
    "evaluation": {"mode": "ALL_MATCHING"},
    "velocityFailurePolicy": "SKIP",
    "rules": [...]
  }
}
```

**Errors**:
- `404` - RuleSet not found
- `409` - RuleSet not APPROVED
- `422` - Compilation failed (validation errors)

### Get Compiled AST
```http
GET /api/v1/rulesets/{ruleset_id}/compiled-ast
```

**Response**: Same as compile endpoint

**Errors**:
- `404` - RuleSet not found or no compiled AST

## Determinism Verification

To verify determinism, compile the same RuleSet twice and compare:

```python
# First compilation
ast1 = compile_ruleset(ruleset_id, db)
json1 = to_canonical_json_string(ast1)

# Second compilation (simulate)
ast2 = compile_ruleset(ruleset_id, db)
json2 = to_canonical_json_string(ast2)

# Should be byte-for-byte identical
assert json1 == json2
```

## Contract with Quarkus Runtime

The compiled AST is the **contract** between this control-plane and the Quarkus runtime engine.

**Runtime responsibilities**:
- Parse AST JSON
- Cache in memory
- Evaluate transactions against rules
- Update velocity counters (Redis)
- Apply actions (ALLOW, BLOCK, FLAG)

**This backend responsibilities**:
- Produce valid, deterministic AST
- Ensure all fields exist
- Validate operators and types
- Version AST (if schema changes)

**Version compatibility**: If AST schema changes, add `astVersion` field and maintain backward compatibility.

## Performance Considerations

**Compilation is NOT real-time**:
- Runs on-demand or after approval
- Can take several seconds for large RuleSets
- Results are cached in database (`compiled_ast` column)

**Optimization targets**:
- Minimize database queries (batch load rules)
- Lazy-load rule field catalog (cache in memory)
- Avoid redundant validation (already validated at approval time)

**Current approach**: Re-validate at compile time for safety. Consider optimization later if needed.

## Future Enhancements

### 1. AST Versioning
Add `astVersion` field to support schema evolution:
```json
{
  "astVersion": "2.0",
  "rulesetId": "...",
  ...
}
```

### 2. Compilation Caching
Cache rule field catalog in memory (avoid DB query per compilation).

### 3. Incremental Compilation
Detect unchanged rules and skip validation (requires change tracking).

### 4. AST Signing
Add cryptographic signature for tamper detection:
```json
{
  "rulesetId": "...",
  "signature": "sha256:abc123...",
  ...
}
```

### 5. Compilation Metrics
Track:
- Compilation duration
- Rule count per RuleSet
- Validation failure rate
- Most common validation errors

## Troubleshooting

### Compilation fails with "Unknown field"
**Cause**: Rule references a field that doesn't exist or is inactive.

**Solution**:
1. Check `rule_fields` table for field existence
2. Verify `is_active = true`
3. Update rule to use valid field

### Compilation fails with "Operator not allowed"
**Cause**: Rule uses operator not in field's `allowed_operators`.

**Solution**:
1. Check field's `allowed_operators` array
2. Update rule to use allowed operator
3. Or extend field's `allowed_operators` (if semantically valid)

### Compiled AST not deterministic
**Cause**: Rules not sorted consistently, or JSON keys not sorted.

**Solution**:
1. Verify `_sort_rules_deterministically` uses stable sort
2. Verify `canonicalize_json` is called on output
3. Check for timestamps or random values in AST

### Compilation succeeds but runtime fails
**Cause**: AST schema mismatch between backend and Quarkus.

**Solution**:
1. Verify AST structure matches Quarkus expectations
2. Check field names (camelCase vs snake_case)
3. Validate enum values (FIRST_MATCH vs FirstMatch)
4. Consider adding AST version field

## References

- [Fraud-Backend.md](../../Fraud-Backend.md) - Overall system design
- [IMPLEMENTATION-GUIDE.md](../../IMPLEMENTATION-GUIDE.md) - Implementation steps
- [app/db/models.py](../db/models.py) - Database models
- [tests/test_compiler.py](../../tests/test_compiler.py) - Compiler tests
