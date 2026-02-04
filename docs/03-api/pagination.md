# Pagination Guide

This guide explains the keyset/cursor-based pagination used in the Fraud Governance API.

## Overview

The API uses keyset/cursor-based pagination for all list endpoints. This provides consistent performance regardless of dataset size and is the only pagination method available.

Keyset pagination is available on all list endpoints:
- `/rules`
- `/rulesets`
- `/approvals`
- `/audit-log`

## Query Parameters

| Parameter | Type | Default | Min | Max | Description |
|-----------|------|---------|-----|-----|-------------|
| `cursor` | string | null | - | - | Base64-encoded cursor from previous response |
| `limit` | integer | 50 | 1 | 100 (1000 for audit-log) | Items per page |
| `direction` | string | next | - | - | Pagination direction: `next` or `prev` |

## Response Format

```json
{
  "items": [...],
  "next_cursor": "eyJpZCI6IjAxSktYMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMiIsImNyZWF0ZWRfYXQiOiIyMDI2LTAxLTE0VDEwOjMwOjQ1WiJ9",
  "prev_cursor": null,
  "has_next": true,
  "has_prev": false,
  "limit": 50
}
```

## Cursor Encoding

Cursors are base64-encoded JSON containing:
- `id`: Entity UUID
- `created_at`: Creation timestamp

**Example cursor decoding:**
```python
import base64
import json

cursor = "eyJpZCI6IjAxSktYMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMiIsImNyZWF0ZWRfYXQiOiIyMDI2LTAxLTE0VDEwOjMwOjQ1WiJ9"
decoded = base64.b64decode(cursor).decode()
data = json.loads(decoded)
# {"id": "01JKX1234567890123456789012", "created_at": "2026-01-14T10:30:45Z"}
```

## Pagination Flow

**First Page (Forward):**
```bash
GET /api/v1/rules?limit=50
```

**Next Page:**
```bash
GET /api/v1/rules?limit=50&cursor=eyJpZCI6Li4u&direction=next
```

**Previous Page:**
```bash
GET /api/v1/rules?limit=50&cursor=eyJpZCI6Li4u&direction=prev
```

## Example Requests

### GET /rules

```bash
# First page
curl -X GET "http://127.0.0.1:8000/api/v1/rules?limit=10" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Next page (using cursor from previous response)
curl -X GET "http://127.0.0.1:8000/api/v1/rules?limit=10&cursor=eyJpZCI6Li4u&direction=next" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

```powershell
# First page
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/rules?limit=10" -Method Get -Headers $headers

# Next page
$cursor = $response.next_cursor
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/rules?limit=10&cursor=$cursor&direction=next" -Method Get -Headers $headers
```

### GET /rulesets

```bash
# First page
curl -X GET "http://127.0.0.1:8000/api/v1/rulesets?limit=20" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Navigate backward
curl -X GET "http://127.0.0.1:8000/api/v1/rulesets?limit=20&cursor=eyJpZCI6Li4u&direction=prev" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### GET /approvals

```bash
# Filter and paginate
curl -X GET "http://127.0.0.1:8000/api/v1/approvals?status=PENDING&limit=50" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### GET /audit-log

```bash
# Audit log supports larger page sizes (up to 1000)
curl -X GET "http://127.0.0.1:8000/api/v1/audit-log?limit=500" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | Array of items for current page |
| `next_cursor` | string/null | Cursor for next page (null if last page) |
| `prev_cursor` | string/null | Cursor for previous page (null if first page) |
| `has_next` | boolean | Whether there is a next page |
| `has_prev` | boolean | Whether there is a previous page |
| `limit` | integer | Number of items per page |

## Pagination Patterns

### Sequential Forward Pagination

```python
import httpx

async def list_all_rules():
    async with httpx.AsyncClient() as client:
        cursor = None
        all_rules = []

        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
                params["direction"] = "next"

            response = await client.get(
                f"{BASE_URL}/rules",
                headers=headers,
                params=params
            )
            data = response.json()

            all_rules.extend(data["items"])

            if not data["has_next"]:
                break

            cursor = data["next_cursor"]

        return all_rules
```

### Bidirectional Pagination

```python
async def paginate_with_navigation():
    # Get first page
    response = await client.get(f"{BASE_URL}/rules", params={
        "limit": 20
    })
    page1 = response.json()

    # Get next page
    response = await client.get(f"{BASE_URL}/rules", params={
        "limit": 20,
        "cursor": page1["next_cursor"],
        "direction": "next"
    })
    page2 = response.json()

    # Go back to first page
    response = await client.get(f"{BASE_URL}/rules", params={
        "limit": 20,
        "cursor": page2["prev_cursor"],
        "direction": "prev"
    })
    page1_again = response.json()
```

### Infinite Scroll UI

```javascript
async function loadRules(cursor = null) {
  const params = new URLSearchParams({
    limit: 20
  });

  if (cursor) {
    params.append("cursor", cursor);
    params.append("direction", "next");
  }

  const response = await fetch(`/api/v1/rules?${params}`);
  const data = await response.json();

  // Append items to UI
  data.items.forEach(rule => {
    // Render rule...
  });

  // Store cursor for next load
  window.nextCursor = data.next_cursor;
  window.hasMore = data.has_next;
}

// Initial load
loadRules();

// Load more on scroll
window.addEventListener("scroll", () => {
  if (window.hasMore && nearBottom()) {
    loadRules(window.nextCursor);
  }
});
```

## Performance

Keyset pagination provides consistent performance regardless of dataset size:

| Dataset Size | Page 1 | Page 100 | Page 1,000 | Page 10,000 |
|--------------|--------|----------|------------|-------------|
| 1,000 items | ~50ms | ~50ms | N/A | N/A |
| 1,000,000 items | ~50ms | ~50ms | ~50ms | ~50ms |

This is because keyset pagination uses indexed WHERE clauses instead of OFFSET scans:

```sql
-- Keyset pagination (consistent performance)
SELECT * FROM rules
WHERE (created_at, rule_id) > ('2026-01-14T10:30:45Z', '01JKX...')
ORDER BY created_at DESC, rule_id DESC
LIMIT 50;
```

## Best Practices

### 1. Handle Pagination State

```python
class PaginationState:
    def __init__(self):
        self.cursor = None
        self.limit = 50

    def to_params(self):
        params = {"limit": self.limit}
        if self.cursor:
            params["cursor"] = self.cursor
            params["direction"] = "next"
        return params

    def update_from_response(self, response):
        if response.get("next_cursor"):
            self.cursor = response["next_cursor"]
```

### 2. Error Handling

```python
async def safe_paginate(endpoint, params):
    try:
        response = await client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 422:
            # Invalid cursor or parameters
            logger.error("Invalid pagination parameters")
            return None
        raise
```

### 3. Cursor Validation

Cursors can become invalid if:
- Data is deleted (cursor points to non-existent item)
- Data expires (audit log retention)
- Manual database modification

**Recovery strategy:**
```python
async def fetch_with_retry(cursor):
    try:
        return await fetch_page(cursor=cursor)
    except ValidationError:
        # Cursor invalid, restart from beginning
        return await fetch_page(cursor=None)
```

### 4. Rate Limit Considerations

When fetching many pages:
- Use larger page sizes (up to max)
- Implement exponential backoff
- Cache results when possible

## Troubleshooting

### Common Issues

**Issue: "Invalid cursor" error**
- Cause: Cursor data was corrupted or malformed
- Solution: Restart pagination from beginning (omit cursor parameter)

**Issue: Missing items when paginating**
- Cause: New items added during pagination
- Solution: Keyset pagination provides consistent snapshot, but may miss new items. Re-query from start if needed.

**Issue: Duplicate items across pages**
- Cause: Items modified/deleted during pagination
- Solution: Deduplicate by ID in client code

**Issue: Performance still slow with keyset pagination**
- Cause: Missing database indexes on `(created_at, id)`
- Solution: Ensure composite indexes exist:
  ```sql
  CREATE INDEX idx_rules_created_id ON fraud_gov.rules(created_at DESC, rule_id DESC);
  CREATE INDEX idx_rulesets_created_id ON fraud_gov.rulesets(created_at DESC, ruleset_id DESC);
  CREATE INDEX idx_approvals_created_id ON fraud_gov.approvals(submitted_at DESC, approval_id DESC);
  CREATE INDEX idx_audit_created_id ON fraud_gov.audit_log(performed_at DESC, audit_id DESC);
  ```

## Testing

### Unit Tests

The project includes comprehensive pagination tests:

```powershell
# Run pagination tests
uv run doppler-test tests/test_unit_keyset_pagination.py -v

# Run specific test
uv run doppler-test tests/test_unit_keyset_pagination.py::TestRuleKeysetPagination::test_list_rules_first_page -v
```

### Test Coverage

- Cursor encoding/decoding
- First page, next page, prev page navigation
- Empty result sets
- Invalid cursor handling
- Boundary conditions (single item, duplicate timestamps)
- All endpoints (rules, rulesets, approvals, audit-log)

## Related Documentation

- [API Reference](reference.md)
- [Implementation Guide](../03-api/reference.md)
- [Testing Examples](reference.md#testing-examples)

---

**Last Updated**: 2026-01-14
