# Card Fraud Rule Engine — Runtime Design Decisions (Authoritative)

> **Purpose**
>
> This document consolidates and locks all major **runtime, scoping, loading, and hot‑reload design decisions** for the Card Fraud Rule Engine.
>
> It is intended to be the **single source of truth** for implementers, reviewers, and future service plans, and should be kept in sync with:
> - card-fraud-rule-engine implementation
> - ruleset publishing contracts
> - transaction‑management ingestion semantics

---

## 1. Deployment & Residency Model

### 1.1 Region vs Country

- **Region** is an **infrastructure boundary** (APAC, EMEA, INDIA)
- **Country** is a **logical and data‑residency boundary** (IN, SG, HK, UK)

Rules are always **country‑scoped**.

The rule engine:
- Is **deployed at region level**
- **Evaluates exactly one country per transaction**
- May **cache rulesets for multiple countries in memory**

No transaction is ever evaluated against rules from multiple countries.

---

## 2. S3 / Object Storage Layout (Locked)

Rulesets are stored **per region + per country**.

```
rulesets/
  prod/
    APAC/
      SG/
        ALLOWLIST-list/
          manifest.json
          v12/ruleset.json
        BLOCKLIST-list/
          manifest.json
          v9/ruleset.json
        CARD_AUTH/
          manifest.json
          v42/ruleset.json
        CARD_MONITORING/
          manifest.json
          v17/ruleset.json
      HK/
        ...
    INDIA/
      IN/
        ...
```

Each country always has **four independent artifacts**:
1. ALLOWLIST List
2. BLOCKLIST List
3. Pre‑Auth Ruleset
4. Post‑Auth Ruleset

All artifacts are:
- Versioned
- Immutable
- Hot‑reloadable independently

---

## 3. Startup Loading Strategy (Locked)

### 3.1 Startup Behavior

At startup, the engine:

1. Lists all countries under its configured region
2. Loads **all rulesets for all countries**
3. Validates for each artifact:
   - checksum (sha256)
   - schema_version
   - country consistency
4. Builds in‑memory structures per country
5. Marks engine **READY only after full load succeeds**

No lazy loading at runtime.

### 3.2 In‑Memory Structure

```
Map<CountryCode, CountryRuleContext>
```

Each `CountryRuleContext` contains:
- ALLOWLIST list
- BLOCKLIST list
- Pre‑auth compiled buckets
- Post‑auth compiled buckets

---

## 4. Hot Reload Strategy (Locked)

### 4.1 Reload Granularity

- Hot reload is **country‑isolated**
- Only rulesets for the **changed country** are reloaded
- Other countries remain unaffected

### 4.2 Reload Failure Policy

**If hot reload fails for a country:**

- ✅ Keep **last known good version** in memory
- 🚨 Emit **high‑severity incident / alert immediately**
- ❌ Do NOT partially apply changes
- ❌ Do NOT block traffic

This guarantees:
- No accidental declines
- No service unavailability
- Clear operational visibility

---

## 5. Rule Evaluation Model

### 5.1 Partition vs Scope

- **Partition**: Country (implicit, enforced by runtime)
- **Scope**: Optional narrowing within a country

Country is **not** a scope dimension.

---

### 5.2 Scope Dimensions (Configurable)

Example (v1):

```yaml
scope_dimensions:
  - network
  - bin
  - mcc
  - logo
```

Scope dimensions are:
- Ordered
- Extensible (BIN added later without runtime change)
- Compiled at publish time

---

### 5.3 Country‑Only Rules

Rules **may omit scope entirely**:

```json
"scope": {}
```

These rules:
- Apply to all transactions in that country
- Are evaluated **last**
- Are allowed to **APPROVE or DECLINE** in pre‑auth

---

## 6. Pre‑Auth Processing (Authoritative)

Evaluation order:

1. ALLOWLIST List (card_id only)
2. BLOCKLIST List (card_id only)
3. Scoped Pre‑Auth Rules
   - Buckets evaluated from **most specific → least specific**
   - Priority order: HIGH → MEDIUM → LOW (within bucket)
   - Stop at **first matching rule**
4. Default APPROVE if no rule matches

All pre‑auth rules **must have a decision**.

Engine failures:
- Return HTTP 200
- decision = APPROVE
- engine_mode = FAIL_OPEN

---

## 7. Post‑Auth Processing

- No decisions
- All matching rules collected
- Same scope narrowing as pre‑auth
- No early exit

---

## 8. Observability & Ops (Locked)

### 8.1 Critical Metrics

- startup_ruleset_load_time
- startup_ruleset_failures
- hot_reload_success_total
- hot_reload_failure_total
- fail_open_total
- degraded_response_total

### 8.2 Alerting

- **Immediate HIGH severity alert** on:
  - Startup load failure
  - Hot reload failure for any country
- Alert must include:
  - country
  - ruleset type
  - version attempted

---

## 9. Performance Expectations

- Rule files loaded once, evaluated in memory
- Scoped bucket evaluation limits rule count per request
- Regex / wildcard rules are acceptable if:
  - Compiled once
  - Cached
  - Not evaluated across entire ruleset

Latency impact of larger rulesets is **linear but bounded**.

Expected behavior:
- Small ruleset → ~1–3ms CPU
- Large ruleset → +1–2ms CPU

No exponential blow‑up.

---

## 10. Non‑Negotiable Invariants

1. One transaction → one country ruleset
2. No cross‑country rule evaluation
3. No DB writes at runtime
4. No S3 access on hot path
5. Fail‑open on engine issues
6. Keep last‑known‑good on reload failure

Any implementation violating these must be rejected.

---

## 11. Status

This document is **LOCKED** for v1 unless changed via ADR.

