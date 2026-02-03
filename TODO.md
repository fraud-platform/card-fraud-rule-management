# TODO - card-fraud-rule-management (governance/compile)

## Goals
- Emit deterministic compiled ruleset JSON consumable by runtime.
- Manifest-driven S3 publishing with checksum.

---

## Summary

| Category | Done | Pending | Blocked |
|----------|------|---------|---------|
| Compiler output/schema | 5 | 0 | 0 |
| Publisher | 3 | 0 | 0 |
| Field registry | 2 | 0 | 0 |
| Dev-only outputs | 2 | 0 | 0 |
| Tests | 3 | 1 (contract tests) | 0 |
| Dependencies | - | 2 (downstream) | 0 |
| Analyst UI Enhancements | 3 | 0 | 0 |

**All items complete!**

---

## Remaining Items (Consolidated)

### 1. Contract tests with rule-engine parser
- **Priority**: Low (optional)
- **Status**: TODO
- **Description**: No cross-project contract tests exist yet

### 2. transaction-management dependencies
- **Priority**: N/A
- **Status**: RESOLVED - Both fields already implemented in transaction-management
- **Items**:
  - `rule_version_id` (UUID) field - DONE
  - `evaluation_type` (AUTH/MONITORING) field - DONE

### 3. Rule Simulation Integration
- **Priority**: Medium
- **Status**: Placeholder implemented
- **Description**: Full integration with transaction-management for actual simulation functionality
- **File**: `app/services/rule_simulation.py:40`
- **Requirements**:
  - Integration with transaction-management's shared query layer
  - Access to historical transaction data
  - A rule execution engine that can evaluate condition trees

---

## Code Quality Improvements (Optional)

### Database Performance (database-specialist-todo.md)
- **Priority 1**: ✅ **COMPLETED** (2026-02-02) - N+1 Query Fixes
  - ✅ Fixed N+1 in `_auto_approve_rule_versions` (app/repos/ruleset_repo.py:68-122)
  - ✅ Fixed N+1 in `compile_ruleset_version` (app/repos/ruleset_repo.py:1013-1055)
  - ✅ Fixed N+1 in `approve_rule_version` (app/repos/rule_repo.py:327-350)

- **Priority 2**: Schema & Data Type Improvements (~2 hours)
  - Change JSON to JSONB (app/db/models.py:126)
  - Add Partial Indexes for Status Queries
  - Add Covering Indexes for Dashboard Queries
  - Add Composite Index for Latest Version Lookups

- **Priority 3**: Caching Layer (~3 hours) - **OPTIONAL (needs Redis)**
  - Implement Redis Cache Infrastructure
  - Cache Active Ruleset Lookups
  - Cache Rule Field Catalog

### Code Simplification (code-simplifier-todo.md)
- **Priority 2**: Consistency Improvements
  - Replace Magic Strings with EntityStatus Enum
  - Create Type Aliases for Permission Dependencies
  - Standardize Logging Patterns

- **Priority 3**: Maintainability Improvements
  - Extract Duplicate Audit Log Helpers
  - Extract Repeated Dict Construction to Helper
  - Simplify `_sort_rules_deterministically`

- **Priority 4**: Dead Code Removal
  - Add Deprecation Warning to Legacy Dependencies
  - Review and Remove Unused Imports

---

## Autonomous Testing Framework Enhancements

### ✅ COMPLETED (2026-02-02)
- ✅ **Line 51**: Implemented `SkipCondition.should_skip()` - Variable existence and equality checks
- ✅ **Line 71**: Implemented `OnConflictHandler.handle_conflict()` - Conflict handling framework
- ✅ **Line 110**: Implemented JSON path validations in `ExpectCondition.validate()`
- ✅ **Line 126**: Implemented `DbAssertion.validate()` - Database state assertion framework
- ✅ **scripts/autonomous_live_test.py:925**: Fixed category capture from scenario data

---

## Completed Items

### Analyst UI Enhancements (Requested 2026-01-27)
- **Rule version read endpoints** (for analyst deep links) - DONE
  - `GET /api/v1/rule-versions/{rule_version_id}` - DONE
  - `GET /api/v1/rules/{rule_id}/versions` - DONE
- **Rule summary endpoint** - DONE
  - `GET /api/v1/rules/{rule_id}/summary` - DONE
- **Rule validation / simulation endpoint** - DONE (Placeholder)
  - `POST /api/v1/rules/simulate` - DONE

### Compiler Output/Schema
- Define/lock compiled ruleset JSON schema version - DONE
- Include top-level fields (schema_version, ruleset_key, etc.) - DONE
- Each rule: rule_id, rule_version_id, priority, scope, when (AST), action - DONE
- Action values match runtime (APPROVE/DECLINE/REVIEW) - DONE

### Publisher
- Publish ruleset.json to S3, then write manifest.json pointer - DONE
- Compute SHA-256 checksum and include in manifest - DONE
- Keep manifest as the only mutable object - DONE
- Include field_registry_version in manifest - DONE

### Field Registry
- Include checksum in field registry artifacts - DONE
- Publish manifest pointer for field registry - DONE

### Tests
- Schema validation tests against compiled-ruleset schema - DONE
- Deterministic serialization tests - DONE
- Action value tests (APPROVE/DECLINE/REVIEW) - DONE

---

## AI Agent Quickstart

```powershell
# Install dependencies
uv sync --extra dev

# Local dev (one command does everything)
uv run local-full-setup --yes
uv run doppler-local

# Tests
uv run doppler-test       # Test against Neon 'test' branch
uv run doppler-prod       # Test against Neon 'prod' branch

# Neon database setup (test + prod)
uv run neon-full-setup --yes              # Full setup: both test and prod
uv run neon-full-setup --config=test --yes  # Test only
uv run neon-full-setup --config=prod --yes  # Prod only

# Regenerate OpenAPI
uv run openapi

# Auth0 bootstrap (idempotent)
uv run auth0-bootstrap --yes
```
