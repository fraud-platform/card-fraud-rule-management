# Expectations from card-fraud-rule-management

This document specifies the data contract that **card-fraud-transaction-management** expects from the **card-fraud-rule-management** (governance) service. This is for **read-only reference data** to enrich analyst views — no writes to governance data.

## Purpose

The transaction management service stores rule matches (`rule_id`, `rule_version`) from the rule engine. To provide a good analyst experience, the UI needs to display:

1. Rule name and description
2. Rule rationale/explanation
3. Rule type (AUTH/MONITORING/BLOCKLIST/ALLOWLIST)
4. Rule condition summary (for understanding why it matched)
5. Rule version history and status

This data is **not for re-evaluation** — only for display and analytics.

## API Endpoints Required

### 1. Get Rule by ID and Version

```
GET /api/v1/rules/{rule_id}?include_versions=true
GET /api/v1/rule-versions/{rule_version_id}
```

**Required Response Fields:**

```json
{
  "rule_id": "UUID (stable identifier)",
  "rule_name": "string (human-readable name)",
  "description": "string (rule rationale, markdown supported)",
  "rule_type": "ALLOWLIST | BLOCKLIST | AUTH | MONITORING",
  "current_version": 1,
  "status": "APPROVED",
  "versions": [
    {
      "rule_version_id": "UUID",
      "version": 1,
      "condition_tree": { /* JSON AST */ },
      "priority": 100,
      "status": "APPROVED",
      "approved_by": "user@example.com",
      "approved_at": "2026-01-15T10:00:00Z"
    }
  ]
}
```

### 2. Batch Get Rules

```
POST /api/v1/rules/batch
Content-Type: application/json

{
  "rule_ids": ["uuid-1", "uuid-2", "uuid-3"]
}
```

**Required Response:**

```json
{
  "items": [
    {
      "rule_id": "uuid-1",
      "rule_name": "...",
      "description": "...",
      "rule_type": "...",
      "current_version": 5,
      "latest_approved_version": {
        "rule_version_id": "...",
        "version": 5,
        "priority": 100,
        "condition_tree": { /* optional, for detail view */ }
      }
    }
  ],
  "not_found": ["uuid-4"]
}
```

**Why batch is needed**: A single transaction can match multiple rules. The UI needs to display all rule details without making N API calls.

### 3. Get Ruleset for Version Context

```
GET /api/v1/rulesets?ruleset_key=CARD_AUTH&status=ACTIVE
```

**Required Response:**

```json
{
  "items": [
    {
      "ruleset_id": "UUID",
      "name": "Q1 2026 Production Rules",
      "rule_type": "AUTH",
      "version": 42,
      "status": "ACTIVE",
      "activated_at": "2026-01-10T00:00:00Z",
      "rule_version_ids": ["uuid-1", "uuid-2", ...]
    }
  ]
}
```

**Why this is needed**: Analysts need to understand which ruleset version was active at the time of a transaction.

## Rule Enrichment Data

### Rule Display Information

For each matched rule, the transaction service needs:

| Field | Source | Purpose |
|-------|--------|---------|
| `rule_id` | Event | Primary key |
| `rule_version` | Event | Version identifier |
| `rule_name` | Governance API | UI display |
| `description` | Governance API | Analyst context |
| `rule_type` | Governance API | Categorization (AUTH/MONITORING) |
| `priority` | Governance API | Understanding evaluation order |
| `severity` | Event | UI sorting/filtering |
| `reason_code` | Event | Human-readable code |
| `condition_tree` | Governance API | Explain why matched (optional for list views) |

### Condition Tree Display

The governance service stores conditions as an AST. For analyst display, we need either:

**Option A**: Pre-computed human-readable summary per rule version:
```json
{
  "condition_summary": "Amount > 5000 AND Cardholder Country != Merchant Country"
}
```

**Option B**: API to render AST to human-readable format:
```
GET /api/v1/rule-versions/{id}/explain
Response: "Amount is greater than 5000 AND Cardholder country is different from merchant country"
```

**Recommended**: Option B with caching, as it provides flexibility for UI formatting.

## Data Freshness Requirements

| Use Case | Freshness | Mechanism |
|----------|-----------|-----------|
| Real-time transaction view | < 5 minutes | Cache rule metadata on ingest |
| Analyst investigation | < 1 hour | Periodic sync or on-demand fetch |
| Dashboard metrics | < 24 hours | Nightly aggregation acceptable |

**Recommendation**: Implement a caching layer in transaction-management that:
1. Caches rule metadata on first encounter
2. Refreshes cache on cache miss or TTL (1 hour)
3. Supports manual cache invalidation webhook from governance

## Suggested New Endpoint

For optimal performance, add a dedicated enrichment endpoint:

```
POST /api/v1/rules/enrich
Content-Type: application/json

{
  "rule_matches": [
    {"rule_id": "uuid", "rule_version": 5},
    {"rule_id": "uuid2", "rule_version": 3}
  ],
  "include_conditions": false  // true for detail view
}
```

**Response:**

```json
{
  "enriched_rules": [
    {
      "rule_id": "uuid",
      "rule_version": 5,
      "rule_name": "High Amount Foreign Transaction",
      "description": "Blocks transactions over $5000 from foreign countries",
      "rule_type": "AUTH",
      "priority": 100,
      "severity": "HIGH",
      "reason_code": "HIGH_AMOUNT_FOREIGN"
    }
  ],
  "not_found": [],
  "cached_at": "2026-01-17T10:00:00Z"
}
```

## Data Not Required

The transaction management service does NOT need:

- Maker/checker workflow data
- Approval history (only current approved status)
- Draft rules
- Rule compilation artifacts
- Audit logs (for transaction display)

## Authentication

All endpoints require:
- JWT authentication via Auth0
- Role: `ANALYST` or higher (read-only access)
- Scopes: `read:rules`, `read:rulesets`

## Rate Limits

For batch/enrich endpoints:
- Allow at least 100 requests/minute
- Support pagination for large result sets

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-17 | Initial specification |

