# Compiler Architecture

## System Context

```
┌─────────────────────────────────────────────────────────────────┐
│                   Fraud Rule Governance API                      │
│                      (Control Plane)                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐  │
│  │   RuleSet    │      │  RuleVersion │      │  RuleField   │  │
│  │  Repository  │──────│  Repository  │      │  Catalog     │  │
│  └──────┬───────┘      └──────────────┘      └──────┬───────┘  │
│         │                                             │           │
│         │                                             │           │
│         ▼                                             ▼           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                           │   │
│  │              COMPILER MODULE (app/compiler/)             │   │
│  │                                                           │   │
│  │  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │   │
│  │  │ Validator  │  │  Compiler  │  │ Canonicalizer    │  │   │
│  │  │            │─▶│            │─▶│                  │  │   │
│  │  │ - Fields   │  │ - Load     │  │ - Sort keys      │  │   │
│  │  │ - Ops      │  │ - Validate │  │ - Deterministic  │  │   │
│  │  │ - Types    │  │ - Sort     │  │ - JSON output    │  │   │
│  │  │ - Values   │  │ - Build    │  │                  │  │   │
│  │  └────────────┘  └────────────┘  └──────────────────┘  │   │
│  │                                                           │   │
│  └────────────────────────────┬──────────────────────────────┘  │
│                                │                                  │
│                                ▼                                  │
│                    ┌─────────────────────┐                       │
│                    │   Compiled AST      │                       │
│                    │   (JSONB in DB)     │                       │
│                    └─────────────────────┘                       │
│                                │                                  │
└────────────────────────────────┼──────────────────────────────────┘
                                 │
                                 │ HTTP GET /compiled-ast
                                 │
                                 ▼
                    ┌─────────────────────┐
                    │  Quarkus Runtime    │
                    │  (Fraud Engine)     │
                    │                     │
                    │  - Parse AST        │
                    │  - Evaluate txns    │
                    │  - Update velocity  │
                    │  - Apply actions    │
                    └─────────────────────┘
```

## Compiler Pipeline

```
Input: RuleSet ID
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│ Step 1: Load RuleSet                                       │
│   - Query: SELECT * FROM rulesets WHERE ruleset_id = ?    │
│   - Verify: status IN (APPROVED, ACTIVE)                  │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 2: Load Attached RuleVersions                         │
│   - Query: SELECT rv.* FROM rule_versions rv               │
│            JOIN ruleset_rules rr ON rv.id = rr.rv_id       │
│            WHERE rr.ruleset_id = ?                         │
│   - Verify: ALL(rv.status = APPROVED)                     │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 3: Load Rule Field Catalog                            │
│   - Query: SELECT * FROM rule_fields WHERE is_active=true  │
│   - Build: field_key -> metadata lookup                   │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 4: Validate Condition Trees                           │
│   FOR EACH rule_version:                                   │
│     - validate_condition_tree(rv.condition_tree)           │
│     - Check: fields exist, ops allowed, types match        │
│   ON ERROR: Raise CompilationError with context            │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 5: Sort Rules Deterministically                       │
│   - Load: Rule entities (for stable rule_id)              │
│   - Sort: ORDER BY priority DESC, rule_id ASC             │
│   - Result: List[(RuleVersion, Rule)]                     │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 6: Map RuleType to Evaluation Mode                    │
│   - ALLOWLIST  → FIRST_MATCH                                │
│   - BLOCKLIST  → FIRST_MATCH                                │
│   - AUTH       → FIRST_MATCH                                │
│   - MONITORING → ALL_MATCHING                               │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 7: Build AST Structure                                │
│   {                                                         │
│     "rulesetId": str(ruleset.ruleset_id),                  │
│     "version": ruleset.version,                            │
│     "ruleType": ruleset.rule_type,                         │
│     "evaluation": {"mode": evaluation_mode},               │
│     "velocityFailurePolicy": "SKIP",                       │
│     "rules": [...]                                         │
│   }                                                         │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│ Step 8: Canonicalize JSON                                  │
│   - Sort all dict keys alphabetically                      │
│   - Recursively process nested structures                  │
│   - Preserve array order (already sorted by priority)      │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
                      Compiled AST (dict)
```

## Validation Flow

```
Condition Tree
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│ Is node a dict?                                         │
│   NO  → ValidationError("node must be dict")            │
│   YES → Continue                                        │
└─────────────────────────────┬───────────────────────────┘
                              │
                              ▼
                    ┌─────────┴─────────┐
                    │                   │
              Contains "and"?     Contains "or"?
                    │                   │
                   YES                 YES
                    │                   │
                    ▼                   ▼
            ┌──────────────┐    ┌──────────────┐
            │ Validate AND │    │ Validate OR  │
            │ - Is list?   │    │ - Is list?   │
            │ - Not empty? │    │ - Not empty? │
            │ - Recurse    │    │ - Recurse    │
            └──────────────┘    └──────────────┘
                    │
                    │
              Contains "not"?
                    │
                   YES
                    │
                    ▼
            ┌──────────────┐
            │ Validate NOT │
            │ - Is dict?   │
            │ - Recurse    │
            └──────────────┘
                    │
                    │
              Contains "field"?
                    │
                   YES
                    │
                    ▼
┌────────────────────────────────────────────────────────────┐
│ Validate Leaf Node                                         │
│   1. Extract: field, op, value                            │
│   2. Check: field exists in catalog                       │
│   3. Check: field.is_active = true                        │
│   4. Check: op in field.allowed_operators                 │
│   5. Check: value type matches field.data_type            │
│   6. Check: multi_value constraint (IN/NOT_IN)            │
│   7. Special: BETWEEN requires exactly 2 values           │
└────────────────────────────────────────────────────────────┘
                    │
                    ▼
              VALID ✓
```

## Data Flow

```
┌──────────────────┐
│   PostgreSQL     │
│                  │
│  ┌────────────┐ │       ┌──────────────┐
│  │ RuleSets   │─┼──────▶│   Compiler   │
│  └────────────┘ │       └──────┬───────┘
│                  │              │
│  ┌────────────┐ │              │
│  │RuleVersions│─┼──────────────┘
│  └────────────┘ │              │
│                  │              │
│  ┌────────────┐ │              │
│  │ RuleFields │─┼──────────────┘
│  └────────────┘ │              │
│                  │              ▼
│                  │       ┌──────────────┐
│                  │       │  Validator   │
│                  │       └──────┬───────┘
│                  │              │
│                  │              ▼
│                  │       ┌──────────────┐
│  ┌────────────┐ │       │Canonicalizer │
│  │ RuleSets   │◀┼───────┤              │
│  │.compiled   │ │       │  (AST dict)  │
│  │    _ast    │ │       └──────────────┘
│  └────────────┘ │
└──────────────────┘
         │
         │ GET /compiled-ast
         │
         ▼
┌──────────────────┐
│   Quarkus        │
│   Runtime        │
│                  │
│  ┌────────────┐ │
│  │AST Parser  │ │
│  └─────┬──────┘ │
│        │         │
│        ▼         │
│  ┌────────────┐ │
│  │ Rule       │ │
│  │ Evaluator  │ │
│  └─────┬──────┘ │
│        │         │
│        ▼         │
│  ┌────────────┐ │
│  │ Action     │ │
│  │ Executor   │ │
│  └────────────┘ │
└──────────────────┘
```

## Component Interactions

```
┌─────────────────────────────────────────────────────────────┐
│                    API Layer                                 │
│                                                              │
│  POST /rulesets/{id}/compile                                │
│  GET  /rulesets/{id}/compiled-ast                           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                Repository Layer                              │
│                                                              │
│  ruleset_repo.compile_ruleset()                             │
│    - Calls compiler                                         │
│    - Stores AST in DB                                       │
│    - Audits action                                          │
│    - Notifies observers                                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Compiler Module                             │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ compiler.compile_ruleset(ruleset_id, db)            │   │
│  │   │                                                  │   │
│  │   ├──▶ Load RuleSet                                 │   │
│  │   ├──▶ Load RuleVersions                            │   │
│  │   ├──▶ Load RuleFields                              │   │
│  │   │                                                  │   │
│  │   ├──▶ validator.validate_condition_tree()          │   │
│  │   │      └─ Validates each rule                     │   │
│  │   │                                                  │   │
│  │   ├──▶ _sort_rules_deterministically()              │   │
│  │   │      └─ ORDER BY priority DESC, rule_id ASC     │   │
│  │   │                                                  │   │
│  │   ├──▶ _get_evaluation_mode()                       │   │
│  │   │      └─ Maps rule_type to mode                  │   │
│  │   │                                                  │   │
│  │   ├──▶ _build_ast()                                 │   │
│  │   │      └─ Constructs AST structure                │   │
│  │   │                                                  │   │
│  │   └──▶ canonicalizer.canonicalize_json()            │   │
│  │          └─ Sorts keys alphabetically               │   │
│  │                                                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Error Propagation

```
Compiler
    │
    ├──▶ NotFoundError ─────────────────────────┐
    │      - RuleSet not found                   │
    │                                            │
    ├──▶ ConflictError ─────────────────────────┤
    │      - RuleSet not APPROVED               │
    │      - RuleVersion not APPROVED           │
    │                                            │
    ├──▶ CompilationError ──────────────────────┤
    │      - Validation failed                   │
    │      - Unknown rule type                   │
    │                                            ▼
    │                                  ┌──────────────────┐
    │                                  │  Error Handler   │
    │                                  │  (API Layer)     │
    │                                  │                  │
    │                                  │  Maps to HTTP:   │
    │                                  │  - 404           │
    │                                  │  - 409           │
    │                                  │  - 422           │
    │                                  └──────────────────┘
    │                                            │
    └──▶ ValidationError ────────────────────────┘
           - Empty tree
           - Unknown field
           - Inactive field
           - Disallowed operator
           - Type mismatch
           - Multi-value violation
```

## Determinism Strategy

```
Same RuleSet ID
       │
       ├──▶ Query 1: Load RuleSet
       │      - Same data (immutable after APPROVED)
       │
       ├──▶ Query 2: Load RuleVersions
       │      - Same versions (frozen by ruleset_rules)
       │      - Same condition_trees (immutable)
       │      - Same priorities (immutable)
       │
       ├──▶ Query 3: Load RuleFields
       │      - Only active fields (stable for compilation)
       │
       ├──▶ Sort: (priority DESC, rule_id ASC)
       │      - Deterministic order (stable UUIDs)
       │
       ├──▶ Map: rule_type → evaluation_mode
       │      - Locked mapping (never changes)
       │
       ├──▶ Build: AST structure
       │      - No timestamps
       │      - No random values
       │      - No environment data
       │
       └──▶ Canonicalize: Sort all keys
              - Alphabetical order at all levels
              │
              ▼
       Same Output (byte-for-byte)
```

## Performance Profile

```
Compilation Time Breakdown:

┌────────────────────────────────────────────────┐
│ Database Queries               30-40%          │  ━━━━━━
│  - Load RuleSet                                │
│  - Load RuleVersions (join)                    │
│  - Load RuleFields                             │
│  - Load Rules (for sorting)                    │
├────────────────────────────────────────────────┤
│ Validation                     40-50%          │  ━━━━━━━━
│  - Parse condition trees                       │
│  - Check fields, ops, types                    │
│  - Deep tree traversal                         │
├────────────────────────────────────────────────┤
│ Sorting                        5-10%           │  ━━
│  - Sort by (priority, rule_id)                 │
├────────────────────────────────────────────────┤
│ AST Building                   5-10%           │  ━━
│  - Construct dict structure                    │
├────────────────────────────────────────────────┤
│ Canonicalization               5-10%           │  ━━
│  - Recursive key sorting                       │
└────────────────────────────────────────────────┘

Total: O(n log n) where n = number of rules
```

## Key Design Patterns

### 1. Pipeline Pattern
Compiler uses a clear 10-step pipeline with explicit data flow.

### 2. Fail-Fast Validation
Errors detected early with detailed context before building AST.

### 3. Immutability
Once approved, rules/rulesets are immutable, enabling determinism.

### 4. Separation of Concerns
- Validator: Structure & semantics
- Compiler: Orchestration & business logic
- Canonicalizer: Output formatting

### 5. Explicit Over Implicit
- Evaluation modes declared, not inferred
- Validation errors include full context
- AST structure self-documenting

## Future Architecture

```
Current:
  Compiler ──▶ DB ──▶ Quarkus

Future (with caching):
  Compiler ──▶ DB ──┬──▶ Quarkus
                    │
                    └──▶ Redis Cache ──▶ Quarkus
                          (AST by hash)

Future (with versioning):
  Compiler ──▶ AST v1 ──▶ DB
           ──▶ AST v2 ──▶ DB
                └──▶ Quarkus (supports both)

Future (with signing):
  Compiler ──▶ AST + Signature ──▶ DB ──▶ Quarkus
                  (verify signature)
```
