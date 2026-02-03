# Compiler

The compiler turns approved RuleSet versions into deterministic AST payloads for runtime consumption.

## Why It Matters

- Deterministic output (same input => same bytes)
- Explicit evaluation semantics
- Compile-time validation of rule fields/operators/values
- Stable ordering for reproducible artifacts

## Key Guarantees

- Rule ordering: priority DESC, rule_id ASC
- Canonical JSON object key ordering
- No random/timestamp noise in compiled payload

Rule type to evaluation mode:
- `ALLOWLIST` -> `FIRST_MATCH`
- `BLOCKLIST` -> `FIRST_MATCH`
- `AUTH` -> `FIRST_MATCH`
- `MONITORING` -> `ALL_MATCHING`

## Main Modules

- `app/compiler/validator.py`
- `app/compiler/compiler.py`
- `app/compiler/canonicalizer.py`

## Compile API Endpoint

```http
POST /api/v1/ruleset-versions/{ruleset_version_id}/compile
```

Authorization in current implementation: `rule:read` permission.

## Validation Scope

The compiler validates condition-tree correctness against the field catalog, including:
- field existence
- operator compatibility
- type compatibility
- multi-value semantics

## How To Verify Determinism

1. Compile the same ruleset version twice.
2. Compare canonical JSON outputs byte-for-byte.
3. Expect exact equality.

## Test Commands

```powershell
uv run doppler-test tests/test_compiler.py -v
uv run doppler-local-test tests/test_integration_compiler.py -v
```

## Related Docs

- `architecture.md`
- `../04-api/reference.md`
- `../adr/0005-deterministic-rule-compiler.md`
