# API Reference

This document is the human-friendly companion to the generated OpenAPI contract.

## Source of Truth

- Machine contract: `docs/03-api/openapi.json`
- Regenerate: `uv run openapi`
- Local Swagger UI: `http://127.0.0.1:8000/docs`

Current OpenAPI path count: **34** (`/api/v1/*`).

## Auth Model

- JWT bearer auth for application endpoints.
- Authorization is permission-based.
- Some read endpoints require authentication but no specific permission dependency.
- Test utility endpoints are enabled only in `local` and `test` environments.

## Permission Matrix

### Rule endpoints

- `POST /api/v1/rules` -> `rule:create`
- `GET /api/v1/rules` -> `rule:read`
- `GET /api/v1/rules/{rule_id}` -> `rule:read`
- `POST /api/v1/rules/{rule_id}/versions` -> `rule:update`
- `POST /api/v1/rule-versions/{rule_version_id}/submit` -> `rule:submit`
- `POST /api/v1/rule-versions/{rule_version_id}/approve` -> `rule:approve`
- `POST /api/v1/rule-versions/{rule_version_id}/reject` -> `rule:reject`
- `GET /api/v1/rule-versions/{rule_version_id}` -> `rule:read`
- `GET /api/v1/rules/{rule_id}/versions` -> `rule:read`
- `GET /api/v1/rules/{rule_id}/summary` -> `rule:read`
- `POST /api/v1/rules/simulate` -> `rule:read`

### Rule field endpoints

- `GET /api/v1/rule-fields` -> authenticated user
- `GET /api/v1/rule-fields/{field_key}` -> authenticated user
- `POST /api/v1/rule-fields` -> `rule_field:create`
- `PATCH /api/v1/rule-fields/{field_key}` -> `rule_field:update`
- `GET /api/v1/rule-fields/{field_key}/metadata` -> authenticated user
- `GET /api/v1/rule-fields/{field_key}/metadata/{meta_key}` -> authenticated user
- `PUT /api/v1/rule-fields/{field_key}/metadata/{meta_key}` -> `rule_field:update`
- `DELETE /api/v1/rule-fields/{field_key}/metadata/{meta_key}` -> `rule_field:delete`

### Field registry endpoints

- `GET /api/v1/field-registry` -> authenticated user
- `GET /api/v1/field-registry/versions` -> authenticated user
- `GET /api/v1/field-registry/versions/{registry_version}` -> authenticated user
- `GET /api/v1/field-registry/versions/{registry_version}/fields` -> authenticated user
- `GET /api/v1/field-registry/next-field-id` -> `rule_field:create`
- `POST /api/v1/field-registry/publish` -> `rule_field:create`

### RuleSet endpoints

- `POST /api/v1/rulesets` -> `ruleset:create`
- `GET /api/v1/rulesets` -> authenticated user
- `GET /api/v1/rulesets/{ruleset_id}` -> authenticated user
- `GET /api/v1/rulesets/{ruleset_id}/versions` -> authenticated user
- `POST /api/v1/rulesets/{ruleset_id}/versions` -> `ruleset:update`
- `GET /api/v1/ruleset-versions/{ruleset_version_id}` -> authenticated user
- `POST /api/v1/ruleset-versions/{ruleset_version_id}/submit` -> `ruleset:submit`
- `POST /api/v1/ruleset-versions/{ruleset_version_id}/approve` -> `ruleset:approve`
- `POST /api/v1/ruleset-versions/{ruleset_version_id}/reject` -> `ruleset:reject`
- `POST /api/v1/ruleset-versions/{ruleset_version_id}/activate` -> `ruleset:activate`
- `POST /api/v1/ruleset-versions/{ruleset_version_id}/compile` -> `rule:read`

### Governance + system endpoints

- `GET /api/v1/approvals` -> authenticated user
- `GET /api/v1/audit-log` -> authenticated user
- `GET /api/v1/health` -> public (optionally token-protected by config)
- `GET /api/v1/readyz` -> public (optionally token-protected by config)
- `GET /api/v1/test-token` -> local/test only
- `GET /api/v1/test-user-token` -> local/test only

## Pagination

Keyset pagination is used on list endpoints that return large collections.

Common query parameters:
- `cursor`
- `limit`
- `direction` (`next` or `prev`)

Common response envelope:

```json
{
  "items": [],
  "next_cursor": null,
  "prev_cursor": null,
  "has_next": false,
  "has_prev": false,
  "limit": 50
}
```

See `pagination.md` for usage details.

## Error Shape

Errors use a structured JSON format:

```json
{
  "error": "ErrorType",
  "message": "Human-readable message",
  "details": {}
}
```

Typical statuses include 400, 401, 403, 404, 409, 422, 429, 500, and 503.

## Notes for Integrators

- Treat `docs/03-api/openapi.json` as the schema contract.
- Regenerate and commit OpenAPI when request/response models change.
- Use Doppler-backed local runs (`uv run doppler-local`) when validating flows end-to-end.
