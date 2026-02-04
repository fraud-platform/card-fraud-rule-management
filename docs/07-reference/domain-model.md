# 📘 Fraud Rule Engine Backend (FastAPI)

## 0. Scope & Non‑Goals

This backend is a **rule governance and compilation system**.

It is responsible for:

* Metadata-driven rule definition
* Maker–checker governance
* Versioning and audit
* Compiling rules into **deterministic AST / JSON DSL**

It is **NOT** responsible for:

* Real-time transaction evaluation
* Velocity counters or state updates
* Authorization decisions

Those are handled by a **Quarkus (Java) runtime engine**.

---

## 1. Design Principles

* Metadata-first (no hardcoded fraud fields)
* Deterministic & explainable
* Auditable by database queries alone
* Minimal APIs (no endpoint explosion)
* Clear separation of control-plane vs runtime

---

## 2. Rule Types & Evaluation Semantics (LOCKED)

| RuleType | Meaning                      | Evaluation Mode |
| -------- | ---------------------------- | --------------- |
| ALLOWLIST | Allow-list                   | FIRST_MATCH     |
| BLOCKLIST | Block-list                   | FIRST_MATCH     |
| AUTH  | Real-time risk checks        | FIRST_MATCH     |
| MONITORING | Post-authorization analytics | ALL_MATCHING    |

> **Important**
> What earlier appeared as `AUTH`/`MONITORING` is explicitly renamed to **AUTH**/**MONITORING**.

Evaluation behavior is **explicitly declared in AST** — never inferred.

---

## 3. Core Domain Model

### 3.1 RuleField (Metadata-driven)

Defines *what dimensions can be used in rules*.

Examples:

* mcc
* merchant_id
* card_hash
* bin
* country
* amount
* velocity_txn_count_5m

**Stable attributes**:

* field_key (immutable)
* display_name
* data_type (STRING, NUMBER, BOOLEAN, DATE, ENUM)
* allowed_operators
* multi_value_allowed
* is_sensitive
* is_active

No schema change is required to add new fields.

---

### 3.2 RuleField Metadata (Extensible)

All non-core attributes live in metadata:

Examples:

* UI grouping & ordering
* Validation hints
* Runtime tags (velocity, geo, device)
* Masking instructions

This enables **unlimited extension without code or schema change**.

---

### 3.3 Rule

A Rule is a **logical expression**, not executable code.

* rule_id (stable)
* name
* rule_type
* condition_tree (JSON)
* priority
* status (DRAFT → PENDING → APPROVED)

Rules are immutable once approved.

---

### 3.4 RuleSet

A RuleSet is the **unit of deployment**.

**Identity Table (`rulesets`)**:
* ruleset_id
* environment (local, dev, test, prod)
* region (APAC, EMEA, INDIA, AMERICAS)
* country (IN, SG, HK, UK, etc.)
* rule_type
* name
* description

**Version Table (`ruleset_versions`)**:
* ruleset_version_id
* ruleset_id (FK to rulesets)
* version (monotonic integer)
* status (DRAFT, PENDING_APPROVAL, APPROVED, ACTIVE, SUPERSEDED)
* approved_by / approved_at
* activated_at

**Membership Table (`ruleset_version_rules`)**:
* ruleset_version_id (FK)
* rule_version_id (FK)

RuleSets snapshot **specific rule versions**.

---

### 3.5 Ruleset Identity vs Versions

**Critical Design Pattern (v1 Schema - 2026-01-19)**

The `rulesets` table has been split into **identity** and **versions** to eliminate an entire class of production bugs where rule drift occurs during deployment.

#### Identity Table (`rulesets`)

Defines **WHAT** the ruleset is—not which snapshot.

```sql
CREATE TABLE fraud_gov.rulesets (
  ruleset_id UUID PRIMARY KEY,
  environment TEXT NOT NULL,
  region      TEXT NOT NULL,
  country     TEXT NOT NULL,
  rule_type   fraud_gov.rule_type NOT NULL,
  name        TEXT,
  description TEXT,
  -- No version here
  -- No compiled_ast here
  UNIQUE (environment, region, country, rule_type)
);
```

**Immutable after creation:**
- `environment`, `region`, `country`, `rule_type` form a natural key
- These attributes never change—if you need a different combination, create a new identity
- `name` and `description` are mutable for documentation purposes

#### Version Table (`ruleset_versions`)

Defines **WHICH** immutable snapshot the runtime uses.

```sql
CREATE TABLE fraud_gov.ruleset_versions (
  ruleset_version_id UUID PRIMARY KEY,
  ruleset_id UUID NOT NULL REFERENCES fraud_gov.rulesets(ruleset_id),
  version INTEGER NOT NULL,
  status fraud_gov.entity_status NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  activated_at TIMESTAMPTZ,
  UNIQUE (ruleset_id, version)
);
```

**Lifecycle States:**
- `DRAFT` → `PENDING_APPROVAL` → `APPROVED` → `ACTIVE` → `SUPERSEDED`
- Only one version per ruleset can be `ACTIVE` at a time
- Runtime consumes artifacts from S3, not this table

#### Membership Table (`ruleset_version_rules`)

Links each version to **exact rule versions** (not rule identities).

```sql
CREATE TABLE fraud_gov.ruleset_version_rules (
  ruleset_version_id UUID NOT NULL REFERENCES fraud_gov.ruleset_versions(ruleset_version_id),
  rule_version_id UUID NOT NULL REFERENCES fraud_gov.rule_versions(rule_version_id),
  PRIMARY KEY (ruleset_version_id, rule_version_id)
);
```

**No rule drift possible:**
- When a rule is updated, it creates a new `rule_version_id`
- Existing `ruleset_version` continues referencing the old `rule_version_id`
- New ruleset version must be explicitly created to include the new rule version

#### Why This Matters

**Before (single table):**
- Updating a rule could silently change behavior of deployed rulesets
- Rollback required tracking which ruleset version was actually deployed
- No clear audit trail of "what exactly was running at time T"

**After (identity + versions):**
- Each version is an immutable snapshot
- Runtime references `ruleset_version_id`, not `ruleset_id`
- Rollback = activate a different `ruleset_version_id`
- Audit trail is exact: "ruleset_version_id X was active from time T to time U"

---

### 3.6 Scope

**Scope (v1 Schema - 2026-01-19)**

Scope defines **when a rule applies** to a transaction. Scope lives on `rule_versions`, not on rulesets.

#### Schema

```sql
CREATE TABLE fraud_gov.rule_versions (
  -- ... other columns ...
  scope JSONB NOT NULL DEFAULT '{}',
  -- ... other columns ...
);
```

#### Scope Format

Scope is stored as JSONB with dimension keys and array values:

```json
{
  "network": ["VISA", "MASTERCARD"],
  "mcc": ["7995", "7999"],
  "bin": ["412345", "412346"],
  "country": ["IN", "SG"],
  "merchant_id": ["merchant-123", "merchant-456"]
}
```

An empty object `{}` means **applies to all transactions** in the country.

#### Scope Dimensions

| Dimension | Example Values | Description |
|-----------|---------------|-------------|
| `network` | `["VISA"]`, `["MASTERCARD"]` | Card network |
| `mcc` | `["7995"]`, `["5967"]` | Merchant category codes |
| `bin` | `["412345"]`, `["521234"]` | Bank identification number (first 6 digits) |
| `country` | `["IN"]`, `["SG"]` | Country code (usually matches ruleset country) |
| `merchant_id` | `["merchant-123"]` | Specific merchant identifiers |

#### Scope Evaluation

1. **Rule-level scope:** Each rule_version has its own scope
2. **Ruleset compilation:** Compiler includes scope in AST for runtime
3. **Runtime matching:** Quarkus evaluates scope per transaction

#### Scope vs Ruleset Country

- **Ruleset `country`:** Data residency and deployment boundary (one ruleset per country)
- **Rule `scope.country`:** Optional filter for multi-country rules (rare; typically rules are country-specific)

Common pattern: Ruleset country = "IN", rule scope = {} → applies to all IN transactions

#### Why Scope on Rule Version, Not Ruleset?

Putting scope on `rule_versions` instead of `rulesets` enables:

1. **Fine-grained control:** Different rules in same ruleset can have different scopes
2. **Flexible composition:** Mix broad-scope and narrow-scope rules in one deployment
3. **Independent evolution:** Update a rule's scope without recompiling entire ruleset
4. **Clear lineage:** Audit trail shows exactly which transactions each rule version affected

---

## 4. Velocity Rules — Architectural Boundary

### Key Decision

❌ Velocity **is NOT accumulated in this backend**.

### Why

* Velocity is transactional state
* Requires atomic updates per transaction
* Needs low-latency reads/writes

This backend:

* **Defines velocity rules**
* **Describes counters and windows**
* **Does not maintain state**

---

### 4.1 Velocity Rule Definition (Here)

Velocity is treated as a **derived RuleField**.

Examples:

* txn_count_last_5m_by_card
* txn_amount_last_1h_by_merchant
* distinct_cards_last_24h_by_mcc

Metadata defines:

* aggregation type (COUNT, SUM, DISTINCT)
* time window
* grouping key(s)

---

### 4.2 Velocity State (Runtime Only)

| Component      | Responsibility     |
| -------------- | ------------------ |
| Redis          | Counters / windows |
| Quarkus        | Update per txn     |
| Backend (this) | Definition only    |

Postgres is **not suitable** for per-txn velocity mutation.

---

## 5. Database Choice

### PostgreSQL (System of Record)

Chosen because:

* Strong governance & audit
* ACID guarantees
* JSONB where flexibility is needed
* Familiar to regulators

MongoDB is rejected for this system.

---

## 6. Logical Data Model (High Level)

Core tables:

* rule_fields
* rule_field_metadata
* rules
* rule_versions
* rulesets
* ruleset_rules
* approvals
* audit_log

No runtime or velocity state is stored here.

---

## 7. API Design (Unified)

Principles:

* RuleType is **data**, not routes
* Same APIs for all rule categories

Examples:

* POST /rules
* GET /rules?rule_type=MONITORING
* POST /rulesets/{id}/compile

No endpoint explosion.

---

## 8. Maker–Checker Lifecycle

### States

1. DRAFT
2. PENDING_APPROVAL
3. APPROVED
4. REJECTED
5. SUPERSEDED

### Rules

* Maker ≠ Checker
* Approved entities are immutable
* Any change → new version

---

## 9. Versioning Strategy

* rule_id is stable
* rule_versions are immutable
* rulesets snapshot versions

Rollback = redeploy older RuleSet version.

---

## 10. AST / JSON DSL (Contract with Quarkus)

```json
{
  "rulesetId": "rs-123",
  "version": 7,
  "ruleType": "MONITORING",
  "evaluation": { "mode": "ALL_MATCHING" },
  "rules": [
    {
      "ruleId": "r-10",
      "priority": 100,
      "when": {
        "and": [
          { "field": "velocity_txn_count_5m_by_card", "op": "GT", "value": 5 },
          { "field": "amount", "op": "GT", "value": 3000 }
        ]
      },
      "action": "FLAG"
    }
  ]
}
```

AST is:

* deterministic
* order-stable
* schema-versioned

---

## 11. Quarkus Consumption Model

* AST fetched or deployed as artifact
* Cached in memory
* Velocity counters updated per txn
* Rules evaluated per declared semantics

No DB calls at runtime.

---

## 12. Security & Compliance

* PAN never stored raw
* Hash + last4 only
* Field-level sensitivity flags
* UI masking via metadata
* Immutable approval records

---

## 13. Audit & Reporting

* All state changes logged
* Old vs new values stored as JSON diff
* Reports generated directly from DB

This system is **audit-first by design**.

---

## 14. Setup Summary

1. Provision PostgreSQL
2. Run the idempotent bootstrap (`uv run db-init` / `uv run db-init-test` / `uv run db-init-prod`)
3. Verify schema + indexes (`uv run db-verify*`)
4. Enable audit triggers
5. Implement maker–checker
6. Implement AST compiler
7. Secure APIs (RBAC)

---

## 15. pgvector Decision

❌ Not required.

Only consider later for:

* Rule similarity detection
* Analyst recommendations

---

## 16. Final Positioning

This backend is a **governance control plane**, not a fraud engine.

Velocity, execution, and transaction state belong strictly to runtime systems.
