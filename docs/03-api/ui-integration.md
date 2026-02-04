# Card Fraud Rule Management API - UI Integration Guide

This document provides information for UI teams integrating with the Card Fraud Rule Management API.

## Overview

The **Card Fraud Rule Management** service provides a REST API for managing fraud detection rules, rule fields, and rulesets. It supports a maker-checker approval workflow for rule changes and handles versioning of rules and rulesets.

### What This Service Does

- **Manages** fraud detection rule definitions (conditions, priorities)
- **Versioning** of rules with immutable versions
- **Maker-Checker workflow** for rule approval (submit, approve, reject)
- **Rule field metadata** management (available fields, operators, types)
- **Ruleset management** for grouping rules by environment/region
- **Compilation** of rulesets to AST for runtime execution

### What This Service Does NOT Do

- Does NOT execute fraud rules in real-time (handled by runtime engine)
- Does NOT store transaction data (handled by transaction-management service)
- Does NOT evaluate velocity checks (handled by Redis in runtime)

## Base URL

- **Local**: `http://localhost:8000`
- **Dev**: Contact DevOps for dev environment URL
- **Test**: Contact DevOps for test environment URL
- **Prod**: Contact DevOps for prod environment URL

All endpoints are prefixed with `/api/v1/`.

## Authentication

All API endpoints require JWT Bearer token authentication via Auth0.

### Getting a Token

1. **For M2M (service-to-service)**: Use Client Credentials flow with Auth0
2. **For user-facing apps**: Use Authorization Code flow with Auth0

### Required Permissions

> **IMPORTANT**: This API uses **permission-based authorization**, NOT role-based.
> Users must have the required permissions in their JWT token (typically mapped from Auth0 roles via RBAC).

| Endpoint | Required Permission |
|----------|---------------------|
| `POST /api/v1/rules` | `rule:create` |
| `GET /api/v1/rules` | `rule:read` |
| `GET /api/v1/rules/{rule_id}` | `rule:read` |
| `POST /api/v1/rules/{rule_id}/versions` | `rule:update` |
| `POST /api/v1/rule-versions/{rule_version_id}/submit` | `rule:submit` |
| `POST /api/v1/rule-versions/{rule_version_id}/approve` | `rule:approve` |
| `POST /api/v1/rule-versions/{rule_version_id}/reject` | `rule:reject` |
| `POST /api/v1/rule-fields` | `rule_field:create` |
| `GET /api/v1/rule-fields` | (authenticated) |
| `PATCH /api/v1/rule-fields/{field_key}` | `rule_field:update` |
| `DELETE /api/v1/rule-fields/{field_key}/metadata/{meta_key}` | `rule_field:delete` |
| `POST /api/v1/rulesets` | `ruleset:create` |
| `POST /api/v1/rulesets/{ruleset_id}/versions` | `ruleset:update` |
| `POST /api/v1/ruleset-versions/{ruleset_version_id}/submit` | `ruleset:submit` |
| `POST /api/v1/ruleset-versions/{ruleset_version_id}/approve` | `ruleset:approve` |
| `POST /api/v1/ruleset-versions/{ruleset_version_id}/reject` | `ruleset:reject` |
| `POST /api/v1/ruleset-versions/{ruleset_version_id}/activate` | `ruleset:activate` |
| `POST /api/v1/ruleset-versions/{ruleset_version_id}/compile` | `rule:read` |
| `GET /api/v1/field-registry` | (authenticated) |
| `GET /api/v1/field-registry/next-field-id` | `rule_field:create` |
| `POST /api/v1/field-registry/publish` | `rule_field:create` |
| `GET /api/v1/approvals` | (authenticated) |
| `GET /api/v1/audit-log` | (authenticated) |

### Auth0 Configuration

Contact DevOps for Auth0 client credentials for your environment.

## API Endpoints

### 1. Health Check Endpoints

#### Basic Health Check

```
GET /api/v1/health
```

**Purpose**: Basic liveness probe.

**Authentication**: Optional - requires `X-Health-Token` header only if `HEALTH_TOKEN` is configured.

**Response** (200 OK):
```json
{
  "ok": true
}
```

#### Readiness Probe

```
GET /api/v1/readyz
```

**Purpose**: Readiness probe that verifies database connectivity.

**Authentication**: Optional - requires `X-Health-Token` header only if `HEALTH_TOKEN` is configured.

**Response** (200 OK):
```json
{
  "ok": true,
  "db": "ok"
}
```

**Response** (503 Service Unavailable):
```json
{
  "ok": false,
  "db": "unavailable"
}
```

### 2. Rule Field Management

#### List Rule Fields

**Purpose**: Get all available rule fields with their metadata.

```
GET /api/v1/rule-fields
Authorization: Bearer <token>
```

**Response** (200 OK):

```json
[
  {
    "field_key": "amount",
    "field_id": 3,
    "display_name": "Amount",
    "description": "Transaction amount in minor currency units",
    "data_type": "NUMBER",
    "allowed_operators": ["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"],
    "multi_value_allowed": false,
    "is_sensitive": false,
    "current_version": 1,
    "version": 1,
    "created_by": "system",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
  }
]
```

**Note**: Standard fields (IDs 1-26) are pre-seeded. Custom fields start from ID 27.

#### Create Rule Field

**Purpose**: Create a new rule field definition.

```
POST /api/v1/rule-fields
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "field_key": "custom_velocity_field",
  "display_name": "Custom Velocity Field",
  "description": "Custom velocity calculation for fraud detection",
  "data_type": "NUMBER",
  "allowed_operators": ["EQ", "GT", "GTE"],
  "multi_value_allowed": false,
  "is_sensitive": false
}
```

**Response** (201 Created):

```json
{
  "field_key": "custom_velocity_field",
  "field_id": 27,
  "display_name": "Custom Velocity Field",
  "description": "Custom velocity calculation for fraud detection",
  "data_type": "NUMBER",
  "allowed_operators": ["EQ", "GT", "GTE"],
  "multi_value_allowed": false,
  "is_sensitive": false,
  "current_version": 1,
  "version": 1,
  "created_by": "user@example.com",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Data Types**: `STRING`, `NUMBER`, `BOOLEAN`, `DATE`, `ENUM`

**Operators**: `EQ`, `NE`, `GT`, `LT`, `GTE`, `LTE`, `BETWEEN`, `IN`, `NOT_IN`, `CONTAINS`, `NOT_CONTAINS`, `STARTS_WITH`, `ENDS_WITH`

#### Get Rule Field

```
GET /api/v1/rule-fields/{field_key}
Authorization: Bearer <token>
```

#### Update Rule Field

**Purpose**: Partially update an existing rule field.

```
PATCH /api/v1/rule-fields/{field_key}
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body** (all fields optional):
```json
{
  "display_name": "Updated Display Name",
  "description": "Updated description"
}
```

**Note**: `field_key` and `field_id` are immutable and cannot be updated.

#### Get Field Metadata

```
GET /api/v1/rule-fields/{field_key}/metadata
Authorization: Bearer <token>
```

**Purpose**: Get all metadata entries for a field (velocity config, UI settings, validation rules).

#### Get Specific Metadata Entry

```
GET /api/v1/rule-fields/{field_key}/metadata/{meta_key}
Authorization: Bearer <token>
```

#### Upsert Metadata

**Purpose**: Create or update metadata for a field.

```
PUT /api/v1/rule-fields/{field_key}/metadata/{meta_key}
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "meta_value": {
    "aggregation": "COUNT",
    "metric": "txn",
    "window": {"value": 10, "unit": "MINUTES"},
    "group_by": ["CARD"]
  }
}
```

#### Delete Metadata Entry

```
DELETE /api/v1/rule-fields/{field_key}/metadata/{meta_key}
Authorization: Bearer <token>
```

**Response**: 204 No Content

### 3. Field Registry Management

#### Get Active Field Registry

**Purpose**: Get information about the active (latest published) field registry.

```
GET /api/v1/field-registry
Authorization: Bearer <token>
```

**Response** (200 OK):

```json
{
  "registry_version": 1,
  "artifact_uri": "fields/registry/v1/fields.json",
  "checksum": "sha256:...",
  "field_count": 26,
  "created_at": "2024-01-15T10:30:00Z",
  "created_by": "system"
}
```

#### List Field Registry Versions

**Purpose**: Get all published field registry versions.

```
GET /api/v1/field-registry/versions
Authorization: Bearer <token>
```

**Response** (200 OK): Array of registry manifests (newest first).

#### Get Specific Registry Version

**Purpose**: Get a specific field registry version details.

```
GET /api/v1/field-registry/versions/{registry_version}
Authorization: Bearer <token>
```

#### Get Fields in Registry Version

**Purpose**: Get all fields that were part of a specific registry version.

```
GET /api/v1/field-registry/versions/{registry_version}/fields
Authorization: Bearer <token>
```

**Response** (200 OK): Array of field definitions.

#### Get Next Field ID

**Purpose**: Get the next available field_id for creating new custom fields.

```
GET /api/v1/field-registry/next-field-id
Authorization: Bearer <token>
```

**Permission**: `rule_field:create`

**Response** (200 OK):

```json
{
  "next_field_id": 27
}
```

**Note**: IDs 1-26 are reserved for standard fields. Custom fields start from 27.

#### Publish Field Registry

**Purpose**: Manually publish a new field registry version from APPROVED field versions.

```
POST /api/v1/field-registry/publish
Authorization: Bearer <token>
```

**Permission**: `rule_field:create`

**Response** (201 Created): Field registry manifest entry.

### 4. Rule Management

#### Create Rule

**Purpose**: Create a new rule with an initial DRAFT version.

```
POST /api/v1/rules
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "rule_name": "High Velocity Check",
  "description": "Decline transactions with high velocity in 10 minutes",
  "rule_type": "VELOCITY",
  "condition_tree": {
    "operator": "AND",
    "conditions": [
      {
        "field": "velocity_txn_count_10m",
        "operator": "GTE",
        "value": 5
      }
    ]
  },
  "priority": 100
}
```

**Rule Types**: `VELOCITY`, `AMOUNT`, `GEO`, `MCC`, `DEVICE`, `COMPOSITE`

**Condition Tree Structure**:

```json
{
  "operator": "AND|OR|NOT",
  "conditions": [
    {
      "field": "field_key",
      "operator": "operator",
      "value": "value"
    }
  ]
}
```

**Response** (201 Created):

```json
{
  "rule_id": "uuid-of-rule",
  "rule_name": "High Velocity Check",
  "description": "Decline transactions with high velocity in 10 minutes",
  "rule_type": "VELOCITY",
  "current_version": 1,
  "status": "DRAFT",
  "created_by": "user|123",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

#### List Rules

**Purpose**: List all rules with keyset pagination.

```
GET /api/v1/rules?limit=50&direction=NEXT
Authorization: Bearer <token>
```

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Items per page (1-100, default: 50) |
| `cursor` | string | Base64-encoded cursor from previous page |
| `direction` | string | `NEXT` or `PREV` for pagination |

**Response** (200 OK):

```json
{
  "items": [...],
  "next_cursor": "base64-encoded-next-cursor",
  "prev_cursor": null,
  "has_next": true,
  "has_prev": false,
  "limit": 50
}
```

#### Get Rule by ID

```
GET /api/v1/rules/{rule_id}
Authorization: Bearer <token>
```

**Response** (200 OK): Full rule object with versions.

#### Create Rule Version

**Purpose**: Create a new version of an existing rule.

```
POST /api/v1/rules/{rule_id}/versions
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "condition_tree": {
    "operator": "AND",
    "conditions": [
      {
        "field": "velocity_txn_count_10m",
        "operator": "GTE",
        "value": 10
      }
    ]
  },
  "priority": 150,
  "expected_rule_version": 1
}
```

**Optimistic Locking**: Include `expected_rule_version` to prevent concurrent edit conflicts.

### 5. Rule Approval Workflow

#### Submit Rule Version

**Purpose**: Submit a rule version for approval.

```
POST /api/v1/rule-versions/{rule_version_id}/submit
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "remarks": "Updated threshold based on new fraud patterns",
  "idempotency_key": "optional-unique-key"
}
```

**Idempotency**: Use `idempotency_key` to ensure duplicate requests don't create multiple approvals.

**Response** (200 OK): Updated rule version with status `PENDING_APPROVAL`.

#### Approve Rule Version

**Purpose**: Approve a submitted rule version.

```
POST /api/v1/rule-versions/{rule_version_id}/approve
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "remarks": "Approved - threshold is appropriate"
}
```

**Response** (200 OK): Updated rule version with status `APPROVED`.

**Side Effects**: Previous approved versions are marked as `SUPERSEDED`.

#### Reject Rule Version

**Purpose**: Reject a submitted rule version.

```
POST /api/v1/rule-versions/{rule_version_id}/reject
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "remarks": "Reject - threshold too aggressive"
}
```

**Response** (200 OK): Updated rule version with status `REJECTED`.

### 6. Ruleset Management

#### Create Ruleset

**Purpose**: Create a new ruleset identity.

```
POST /api/v1/rulesets
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "environment": "prod",
  "region": "INDIA",
  "country": "IN",
  "rule_type": "VELOCITY",
  "name": "India Prod Velocity Rules",
  "description": "Velocity rules for India prod"
}
```

**Uniqueness**: One ruleset per unique combination of (environment, region, country, rule_type).

#### List Rulesets

**Purpose**: List ruleset identities with optional filters.

```
GET /api/v1/rulesets?limit=50&rule_type=VELOCITY&environment=prod
Authorization: Bearer <token>
```

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Items per page (1-100, default: 50) |
| `cursor` | string | Base64-encoded cursor from previous page |
| `direction` | string | `NEXT` or `PREV` for pagination |
| `rule_type` | string | Filter by rule type |
| `environment` | string | Filter by environment |
| `region` | string | Filter by region |
| `country` | string | Filter by country |

**Response** (200 OK): Paginated list of rulesets.

#### Get Ruleset

```
GET /api/v1/rulesets/{ruleset_id}
Authorization: Bearer <token>
```

#### List Ruleset Versions

**Purpose**: List all versions of a ruleset.

```
GET /api/v1/rulesets/{ruleset_id}/versions?limit=50&status=APPROVED
Authorization: Bearer <token>
```

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Items per page (1-100, default: 50) |
| `cursor` | string | Base64-encoded cursor from previous page |
| `direction` | string | `NEXT` or `PREV` for pagination |
| `status` | string | Filter by status (DRAFT, PENDING_APPROVAL, APPROVED, ACTIVE, SUPERSEDED, REJECTED) |

#### Create Ruleset Version

**Purpose**: Create a new version of a ruleset with attached rules.

```
POST /api/v1/rulesets/{ruleset_id}/versions
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "rule_version_ids": [
    "uuid-of-rule-version-1",
    "uuid-of-rule-version-2"
  ]
}
```

**Response** (201 Created): New ruleset version with status `DRAFT`.

#### Get Ruleset Version

```
GET /api/v1/ruleset-versions/{ruleset_version_id}
Authorization: Bearer <token>
```

**Response**: Ruleset version with attached rules included.

### 7. Ruleset Approval Workflow

#### Submit Ruleset Version

**Purpose**: Submit a ruleset version for approval.

```
POST /api/v1/ruleset-versions/{ruleset_version_id}/submit
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "idempotency_key": "optional-unique-key"
}
```

#### Approve Ruleset Version

**Purpose**: Approve a ruleset version (triggers publishing to S3).

```
POST /api/v1/ruleset-versions/{ruleset_version_id}/approve
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "remarks": "Approved for production deployment"
}
```

**Side Effects**: Approved ruleset is compiled and published to S3 for runtime consumption.

#### Reject Ruleset Version

**Purpose**: Reject a ruleset version.

```
POST /api/v1/ruleset-versions/{ruleset_version_id}/reject
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "remarks": "Reject - incomplete rule coverage"
}
```

#### Activate Ruleset Version

**Purpose**: Activate an approved ruleset version (makes it live for runtime).

```
POST /api/v1/ruleset-versions/{ruleset_version_id}/activate
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:

```json
{
  "remarks": "Activating for production deployment"
}
```

**Response**: Ruleset version with status `ACTIVE`.

#### Compile Ruleset Version

**Purpose**: Compile a ruleset version to AST (in-memory preview).

```
POST /api/v1/ruleset-versions/{ruleset_version_id}/compile
Authorization: Bearer <token>
```

**Response** (200 OK):

```json
{
  "ast": {
    "version": "1.0",
    "rules": [...]
  },
  "compiled_at": "2024-01-15T10:30:00Z"
}
```

### 8. Approvals & Audit

#### List Approvals

**Purpose**: List all pending/approved/rejected items.

```
GET /api/v1/approvals?status=pending&entity_type=rule
Authorization: Bearer <token>
```

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Items per page (1-100, default: 50) |
| `cursor` | string | Base64-encoded cursor from previous page |
| `direction` | string | `NEXT` or `PREV` for pagination |
| `status` | string | Filter by approval status |
| `entity_type` | string | Filter by entity type (RULE_VERSION, RULESET_VERSION) |

#### Get Audit Log

**Purpose**: Get audit trail of all changes.

```
GET /api/v1/audit-log?entity_type=rule&action=approve
Authorization: Bearer <token>
```

**Query Parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Items per page (1-1000, default: 100) |
| `cursor` | string | Base64-encoded cursor from previous page |
| `direction` | string | `NEXT` or `PREV` for pagination |
| `entity_type` | string | Filter by entity type |
| `entity_id` | string | Filter by specific entity ID |
| `action` | string | Filter by action (CREATE, UPDATE, DELETE, APPROVE, REJECT, SUBMIT, ACTIVATE) |
| `performed_by` | string | Filter by user who performed the action |
| `since` | string | ISO 8601 datetime filter (start of range) |
| `until` | string | ISO 8601 datetime filter (end of range) |

### 9. Test Utilities (Local/Test Only)

These endpoints are **ONLY available in non-production environments**.

#### Generate M2M Test Token

**Purpose**: Generate a real Auth0 M2M token for Swagger UI testing.

```
GET /api/v1/test-token
```

**Note**: M2M tokens represent the CLIENT, not a USER. Use `/test-user-token` for maker-checker workflow testing.

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "issued_at": "2024-01-15T10:30:00Z",
  "token_category": "M2M (Client Credentials)",
  "limitations": [
    "Token represents client, not user",
    "maker=checker validation will REJECT approval requests"
  ]
}
```

#### Generate User Test Token

**Purpose**: Generate tokens for specific test users (maker-checker testing).

```
GET /api/v1/test-user-token?user=maker
```

**Query Parameters**:
- `user`: `maker`, `checker`, or `admin`

**Response**:
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user_type": "maker",
  "user_email": "test-rule-maker@fraud-platform.test",
  "maker_checker_compatible": true
}
```

## Status Values

### Rule Version Status

| Status | Description |
|--------|-------------|
| `DRAFT` | Initial state, editable |
| `PENDING_APPROVAL` | Submitted for approval, read-only |
| `APPROVED` | Approved and active |
| `SUPERSEDED` | Replaced by newer version |
| `REJECTED` | Rejected by checker |

### Ruleset Version Status

| Status | Description |
|--------|-------------|
| `DRAFT` | Initial state, editable |
| `PENDING_APPROVAL` | Submitted for approval |
| `APPROVED` | Approved, published to S3 |
| `ACTIVE` | Currently in use |
| `SUPERSEDED` | Replaced by newer version |
| `REJECTED` | Rejected by checker |

## Error Handling

All errors follow standard HTTP status codes with JSON response:

```json
{
  "error": "Error type",
  "message": "Human-readable message",
  "details": {
    "field": "rule_name",
    "reason": "Invalid format"
  }
}
```

**Common Error Codes**:

| Status | Description |
|--------|-------------|
| `400 Bad Request` | Validation error |
| `401 Unauthorized` | Missing/invalid token |
| `403 Forbidden` | Insufficient permissions |
| `404 Not Found` | Resource does not exist |
| `409 Conflict` | Resource already exists or optimistic lock failure |
| `422 Unprocessable Entity` | Validation error (detailed) |

## Maker-Checker Workflow

The rule management follows a maker-checker approval pattern:

1. **Maker** creates/edits a rule → Status: `DRAFT`
2. **Maker** submits for approval → Status: `PENDING_APPROVAL`
3. **Checker** reviews and either:
   - **Approves** → Status: `APPROVED` (now active)
   - **Rejects** → Status: `REJECTED` (can be resubmitted)

**Important**: Maker and Checker must be different users. A user cannot approve their own submission.

## OpenAPI Specification

Full OpenAPI 3.1 specification available at:
- Development: `http://localhost:8000/openapi.json`
- Generated file: `docs/03-api/openapi.json`

Regenerate with: `uv run openapi`

## Metrics Endpoint

Prometheus metrics endpoint for monitoring:

```
GET /metrics
X-Metrics-Token: <token>
```

**Note**: Always requires authentication via `X-Metrics-Token` header.

## Support

- **API Issues**: Create ticket in project repository
- **Auth0 Issues**: Contact DevOps/Security team
- **Permission Issues**: Contact DevOps for role/permission assignment
