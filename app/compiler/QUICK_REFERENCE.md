# Compiler Quick Reference

## Import Statements

```python
# Main compilation
from app.compiler.compiler import compile_ruleset

# Validation
from app.compiler.validator import validate_condition_tree

# Canonicalization
from app.compiler.canonicalizer import (
    canonicalize_json,
    to_canonical_json_string,
    to_canonical_json_pretty
)
```

## Basic Usage

### Compile a RuleSet

```python
from app.compiler.compiler import compile_ruleset
from uuid import UUID

# In your repository or service
def compile_my_ruleset(db: Session, ruleset_id_str: str):
    ruleset_id = UUID(ruleset_id_str)
    compiled_ast = compile_ruleset(ruleset_id, db)
    return compiled_ast
```

### Validate Condition Tree

```python
from app.compiler.validator import validate_condition_tree

rule_fields = {
    "amount": {
        "data_type": "NUMBER",
        "allowed_operators": ["GT", "LT", "BETWEEN"],
        "multi_value_allowed": False,
        "is_active": True
    }
}

condition_tree = {
    "and": [
        {"field": "amount", "op": "GT", "value": 1000},
        {"field": "amount", "op": "LT", "value": 10000}
    ]
}

# Raises ValidationError if invalid
validate_condition_tree(condition_tree, rule_fields)
```

### Canonicalize JSON

```python
from app.compiler.canonicalizer import canonicalize_json

data = {"z": 1, "a": {"c": 2, "b": 3}}
canonical = canonicalize_json(data)
# Result: {"a": {"b": 3, "c": 2}, "z": 1}
```

## API Endpoints

### Compile RuleSet

```http
POST /api/v1/rulesets/{ruleset_id}/compile
Authorization: Bearer {token}
```

**Response**:
```json
{
  "ruleset_id": "uuid",
  "compiled_ast": {
    "rulesetId": "uuid",
    "version": 1,
    "ruleType": "MONITORING",
    "evaluation": {"mode": "ALL_MATCHING"},
    "velocityFailurePolicy": "SKIP",
    "rules": [...]
  }
}
```

### Get Compiled AST

```http
GET /api/v1/rulesets/{ruleset_id}/compiled-ast
Authorization: Bearer {token}
```

## AST Structure Reference

```json
{
  "rulesetId": "string (UUID)",
  "version": "integer",
  "ruleType": "ALLOWLIST|BLOCKLIST|AUTH|MONITORING",
  "evaluation": {
    "mode": "FIRST_MATCH|ALL_MATCHING"
  },
  "velocityFailurePolicy": "SKIP|FAIL_OPEN|FAIL_CLOSED",
  "rules": [
    {
      "ruleId": "string (UUID)",
      "ruleVersionId": "string (UUID)",
      "priority": "integer",
      "when": {
        "and|or": [...],
        "not": {...},
        "field": "string",
        "op": "EQ|GT|LT|IN|...",
        "value": "any"
      },
      "action": "ALLOW|BLOCK|FLAG"
    }
  ]
}
```

## Condition Tree Examples

### Condition Tree Format Options

The validator supports **two formats** for condition trees:

#### Format 1: Lowercase Keys (Original)
```json
{
  "and": [
    {"field": "amount", "op": "GT", "value": 1000},
    {"or": [
      {"field": "is_international", "op": "EQ", "value": true},
      {"field": "mcc", "op": "IN", "value": ["5967", "7995"]}
    ]}
  ]
}
```

#### Format 2: Type-Based (Alternative)
```json
{
  "type": "AND",
  "conditions": [
    {
      "type": "CONDITION",
      "field": "amount",
      "operator": "GT",
      "value": 1000
    },
    {
      "type": "OR",
      "conditions": [
        {"type": "CONDITION", "field": "is_international", "operator": "EQ", "value": true},
        {"type": "CONDITION", "field": "mcc", "operator": "IN", "value": ["5967", "7995"]}
      ]
    }
  ]
}
```

**Note**: For type-based format, use `"operator"` instead of `"op"` for leaf conditions.

### Simple Condition

```json
{
  "field": "mcc",
  "op": "EQ",
  "value": "5967"
}
```

### AND Composition

```json
{
  "and": [
    {"field": "amount", "op": "GT", "value": 1000},
    {"field": "mcc", "op": "IN", "value": ["5967", "5968"]}
  ]
}
```

### OR Composition

```json
{
  "or": [
    {"field": "is_international", "op": "EQ", "value": true},
    {"field": "amount", "op": "GT", "value": 5000}
  ]
}
```

### NOT Composition

```json
{
  "not": {
    "field": "merchant_id",
    "op": "IN",
    "value": ["trusted-merchant-1", "trusted-merchant-2"]
  }
}
```

### Nested Composition

```json
{
  "and": [
    {"field": "amount", "op": "GT", "value": 1000},
    {
      "or": [
        {"field": "is_international", "op": "EQ", "value": true},
        {"field": "mcc", "op": "IN", "value": ["5967", "7995"]}
      ]
    }
  ]
}
```

### BETWEEN Operator

```json
{
  "field": "amount",
  "op": "BETWEEN",
  "value": [100, 1000]
}
```

## Evaluation Mode Mapping

```python
RULE_TYPE_TO_EVALUATION_MODE = {
    "ALLOWLIST": "FIRST_MATCH",    # Allow-list
    "BLOCKLIST": "FIRST_MATCH",    # Block-list
    "AUTH": "FIRST_MATCH",         # Real-time
    "MONITORING": "ALL_MATCHING"   # Analytics
}
```

## Supported Operators

| Operator | Description | Value Type | Example |
|----------|-------------|------------|---------|
| `EQ` | Equal | Single | `{"op": "EQ", "value": "5967"}` |
| `NE` | Not Equal | Single | `{"op": "NE", "value": "blocked"}` |
| `GT` | Greater Than | Single (number) | `{"op": "GT", "value": 1000}` |
| `GTE` | Greater Than or Equal | Single (number) | `{"op": "GTE", "value": 500}` |
| `LT` | Less Than | Single (number) | `{"op": "LT", "value": 100}` |
| `LTE` | Less Than or Equal | Single (number) | `{"op": "LTE", "value": 50}` |
| `IN` | In List | List | `{"op": "IN", "value": ["a", "b"]}` |
| `NOT_IN` | Not In List | List | `{"op": "NOT_IN", "value": ["x"]}` |
| `BETWEEN` | Between Range | List (2 items) | `{"op": "BETWEEN", "value": [10, 100]}` |
| `CONTAINS` | String Contains | Single (string) | `{"op": "CONTAINS", "value": "fraud"}` |
| `STARTS_WITH` | String Starts With | Single (string) | `{"op": "STARTS_WITH", "value": "test"}` |
| `ENDS_WITH` | String Ends With | Single (string) | `{"op": "ENDS_WITH", "value": ".com"}` |
| `REGEX` | Regex Match | Single (string) | `{"op": "REGEX", "value": "^[0-9]+$"}` |

## Data Types

| Data Type | Python Type | Example Values |
|-----------|-------------|----------------|
| `STRING` | `str` | `"5967"`, `"merchant-id"` |
| `NUMBER` | `int`, `float` | `1000`, `99.99` |
| `BOOLEAN` | `bool` | `true`, `false` |
| `DATE` | `str` (ISO 8601) | `"2026-01-02T10:30:00Z"` |
| `ENUM` | `str` (from allowed set) | `"APPROVED"`, `"PENDING"` |

## Error Types

### ValidationError (400)

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

### CompilationError (422)

```python
CompilationError(
    "Condition tree validation failed for rule version abc-123",
    details={
        "ruleset_id": "rs-456",
        "rule_version_id": "abc-123",
        "rule_id": "r-10",
        "error": "Unknown field 'invalid_field'"
    }
)
```

### ConflictError (409)

```python
ConflictError(
    "RuleSet must be APPROVED or ACTIVE to compile (status: DRAFT)",
    details={
        "ruleset_id": "rs-456",
        "status": "DRAFT"
    }
)
```

### NotFoundError (404)

```python
NotFoundError(
    "RuleSet not found",
    details={
        "ruleset_id": "rs-456"
    }
)
```

## Common Patterns

### Validate Before Saving

```python
from app.compiler.validator import validate_condition_tree

def create_rule_version(db, payload):
    # Load field catalog
    fields = {f.field_key: {...} for f in db.query(RuleField).all()}

    # Validate condition tree
    validate_condition_tree(payload["condition_tree"], fields)

    # Save if valid
    rule_version = RuleVersion(**payload)
    db.add(rule_version)
    db.commit()
```

### Compile and Store

```python
from app.compiler.compiler import compile_ruleset

def compile_and_store(db, ruleset_id):
    # Compile
    compiled_ast = compile_ruleset(ruleset_id, db)

    # Store
    ruleset = db.query(RuleSet).get(ruleset_id)
    ruleset.compiled_ast = compiled_ast
    db.commit()

    return compiled_ast
```

### Verify Determinism

```python
from app.compiler.compiler import compile_ruleset
from app.compiler.canonicalizer import to_canonical_json_string

# Compile twice
ast1 = compile_ruleset(ruleset_id, db)
ast2 = compile_ruleset(ruleset_id, db)

# Compare as JSON strings
json1 = to_canonical_json_string(ast1)
json2 = to_canonical_json_string(ast2)

assert json1 == json2  # Must be identical
```

## Testing

### Run All Compiler Tests

```bash
uv run pytest tests/test_compiler.py -v
```

### Run Specific Test Class

```bash
uv run pytest tests/test_compiler.py::TestValidator -v
```

### Run Single Test

```bash
uv run pytest tests/test_compiler.py::TestValidator::test_valid_simple_condition -v
```

### Test with Coverage

```bash
uv run pytest tests/test_compiler.py --cov=app.compiler --cov-report=term-missing
```

## Troubleshooting

### "Unknown field" Error

**Problem**: Rule references a field that doesn't exist.

**Solution**:
```sql
-- Check field exists
SELECT * FROM fraud_gov.rule_fields WHERE field_key = 'your_field';

-- Check field is active
SELECT * FROM fraud_gov.rule_fields WHERE field_key = 'your_field' AND is_active = true;
```

### "Operator not allowed" Error

**Problem**: Using an operator not in field's allowed_operators.

**Solution**:
```sql
-- Check allowed operators
SELECT field_key, allowed_operators
FROM fraud_gov.rule_fields
WHERE field_key = 'your_field';

-- Update allowed operators (if valid)
UPDATE fraud_gov.rule_fields
SET allowed_operators = array_append(allowed_operators, 'NEW_OP')
WHERE field_key = 'your_field';
```

### "Type mismatch" Error

**Problem**: Value type doesn't match field data_type.

**Solution**: Check field data type and use correct value type:
- STRING: `"value"`
- NUMBER: `1000` (not `"1000"`)
- BOOLEAN: `true` (not `"true"`)

### Compilation is Slow

**Problem**: Large rulesets take seconds to compile.

**Solutions**:
1. Cache rule field catalog in memory
2. Add indexes on foreign keys
3. Use batch loading for related entities
4. Consider incremental compilation

## Performance Tips

1. **Batch Compile**: Don't compile on every rule change, wait for approval.
2. **Cache Fields**: Load rule field catalog once, reuse across compilations.
3. **Index Database**: Ensure indexes on ruleset_id, rule_id, rule_version_id.
4. **Async Compilation**: Use background jobs for large rulesets.
5. **Monitor Metrics**: Track compilation time, rule count, error rate.

## Security Considerations

1. **Validate Input**: Always validate condition trees before saving.
2. **Sanitize Values**: Be careful with REGEX operators (ReDoS attacks).
3. **Limit Complexity**: Set max depth for nested conditions.
4. **Audit Changes**: Log all compilations with user context.
5. **Version ASTs**: Consider adding signatures for tamper detection.

## Integration Checklist

- [ ] Database connection configured
- [ ] RuleSet table has compiled_ast column (JSONB)
- [ ] RuleFields catalog populated
- [ ] API endpoints registered
- [ ] Error handlers configured
- [ ] Audit logging enabled
- [ ] Tests passing
- [ ] Documentation reviewed

## Quick Debugging

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Compile with detailed logs
from app.compiler.compiler import compile_ruleset
compiled_ast = compile_ruleset(ruleset_id, db)

# Pretty print AST
from app.compiler.canonicalizer import to_canonical_json_pretty
print(to_canonical_json_pretty(compiled_ast))
```

## Command Line Tools

### Validate a Condition Tree

```python
# save as validate_tree.py
from app.compiler.validator import validate_condition_tree
import json
import sys

tree = json.loads(sys.argv[1])
fields = {...}  # Load from DB

try:
    validate_condition_tree(tree, fields)
    print("Valid!")
except Exception as e:
    print(f"Invalid: {e}")
```

### Compile a RuleSet

```python
# save as compile.py
from app.compiler.compiler import compile_ruleset
from app.core.db import get_db
import sys

ruleset_id = sys.argv[1]
db = next(get_db())
ast = compile_ruleset(ruleset_id, db)
print(json.dumps(ast, indent=2))
```
