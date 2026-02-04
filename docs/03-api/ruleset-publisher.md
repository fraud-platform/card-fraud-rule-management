# Ruleset Publisher Service - Quick Reference

**Status:** ✅ Implemented (2026-01-15)

**Purpose:** Automatically publish compiled ruleset artifacts to S3-compatible storage when a RuleSet is approved.

---

## Overview

When a RuleSet is approved, the Ruleset Publisher Service:
1. Compiles the RuleSet into a deterministic AST
2. Serializes the AST to canonical JSON
3. Computes SHA-256 checksum (`sha256:<lowercase-hex>`)
4. Publishes the artifact to storage (filesystem or S3) using an immutable, versioned key
5. Records the publication in the governance audit record (DB `ruleset_manifest` table)
6. Writes/updates the runtime source-of-truth pointer file (`manifest.json`) in object storage

**Key Characteristic:** Publishing is atomic with approval. If publishing fails, the approval is rolled back.

Source-of-truth model (locked):
- DB `ruleset_manifest` is the governance source of truth (approvals/audit/compliance).
- S3/MinIO `manifest.json` is the runtime source of truth (runtime consumption).
- Runtime never reads DB.
- Governance never infers runtime state from S3.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     RuleSet Approval Flow                    │
└─────────────────────────────────────────────────────────────┘

POST /api/v1/rulesets/{id}/approve
    ↓
1. Validate maker-checker rules
    ↓
2. Update RuleSet status to APPROVED
    ↓
3. Compile RuleSet → AST
    ↓
4. Publish artifact to storage
  ├─→ Filesystem: .local/ruleset-artifacts/rulesets/{environment}/{ruleset_key}/v{ruleset_version}/ruleset.json
  └─→ S3/MinIO: s3://{bucket}/rulesets/{environment}/{ruleset_key}/v{ruleset_version}/ruleset.json
    ↓
5. Insert row into ruleset_manifest (governance audit)
    ↓
6. Write/update runtime pointer: s3://{bucket}/rulesets/{environment}/{ruleset_key}/manifest.json
  ↓
7. Commit transaction (or rollback if any step fails)
```

---

## Rule Type Mapping

| RuleSet Type | Runtime Key | Description | Published? |
|--------------|-------------|-------------|------------|
| `AUTH` | `CARD_AUTH` | Decisioning rules (FIRST_MATCH) | ✅ Yes |
| `MONITORING` | `CARD_MONITORING` | Analytics rules (ALL_MATCHING) | ✅ Yes |
| `ALLOWLIST` | *(none)* | Compiled within AUTH context | ❌ No |
| `BLOCKLIST` | *(none)* | Compiled within AUTH context | ❌ No |

**Why only AUTH and MONITORING?**
- Runtime engines only execute two rulesets: `CARD_AUTH` and `CARD_MONITORING`
- `ALLOWLIST` and `BLOCKLIST` are governance-only types that get compiled within the AUTH context
- This mapping is enforced at the publisher level to prevent invalid publications

---

## Storage Backends

### Filesystem (Local Development)

**Configuration:**
```bash
RULESET_ARTIFACT_BACKEND=filesystem
```

**Artifact Location:**
```
.local/ruleset-artifacts/
└── rulesets/
  └── local/
    ├── CARD_AUTH/
    │   ├── manifest.json
    │   └── v1/
    │       └── ruleset.json
    └── CARD_MONITORING/
      ├── manifest.json
      └── v1/
        └── ruleset.json
```

**Use Case:** Local development without Docker or MinIO

### S3/MinIO (Prod)

**Configuration:**
```bash
RULESET_ARTIFACT_BACKEND=s3
S3_ENDPOINT_URL=http://localhost:9000  # MinIO
S3_BUCKET_NAME=fraud-gov-artifacts
S3_ACCESS_KEY_ID=<access-key>
S3_SECRET_ACCESS_KEY=<secret-key>
S3_REGION=us-east-1
S3_FORCE_PATH_STYLE=true  # true for MinIO, false for AWS S3
```

**Artifact Location:**
```
s3://fraud-gov-artifacts/
└── rulesets/
  ├── local/
  │   ├── CARD_AUTH/
  │   │   ├── manifest.json
  │   │   └── v1/
  │   │       └── ruleset.json
  │   └── CARD_MONITORING/
  │       ├── manifest.json
  │       └── v1/
  │           └── ruleset.json
  ├── test/
  │   └── ...
  └── prod/
    └── ...
```

**Use Case:** Production deployment or local testing with MinIO

---

## Governance Audit Record (DB)

The governance service records every published artifact in the `ruleset_manifest` table.

This is:
- Required for governance (approvals, audit, traceability, compliance)
- Runtime-opaque (runtime never reads this table)

Important: this DB table is not the runtime manifest. Runtime consumption is driven only by the object-storage `manifest.json` pointer file.

```sql
CREATE TABLE fraud_gov.ruleset_manifest (
  ruleset_manifest_id UUID PRIMARY KEY,
  environment TEXT NOT NULL,           -- dev, test, prod
  ruleset_key TEXT NOT NULL,           -- CARD_AUTH | CARD_MONITORING
  ruleset_version INTEGER NOT NULL,    -- monotonically increasing
  artifact_uri TEXT NOT NULL,          -- e.g., s3://{bucket}/rulesets/{environment}/{ruleset_key}/v{ruleset_version}/ruleset.json
  checksum TEXT NOT NULL,              -- sha256:<lowercase-hex>
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT NOT NULL
);

-- Unique constraint prevents duplicate versions
CREATE UNIQUE INDEX uq_ruleset_manifest
  ON fraud_gov.ruleset_manifest(environment, ruleset_key, ruleset_version);
```

### Query Examples

```sql
-- View all published artifacts
SELECT
    environment,
    ruleset_key,
    ruleset_version,
    artifact_uri,
    checksum,
    created_at,
    created_by
FROM fraud_gov.ruleset_manifest
ORDER BY created_at DESC;

-- Get latest version for a ruleset
SELECT
    environment,
    ruleset_key,
    ruleset_version,
    artifact_uri
FROM fraud_gov.ruleset_manifest
WHERE environment = 'prod'
  AND ruleset_key = 'CARD_AUTH'
ORDER BY ruleset_version DESC
LIMIT 1;

-- Verify artifact integrity
SELECT
    ruleset_key,
    ruleset_version,
    checksum,
    created_at
FROM fraud_gov.ruleset_manifest
WHERE environment = 'prod'
ORDER BY created_at DESC
LIMIT 10;
```

---

## Runtime Source of Truth (Object Storage `manifest.json`)

Runtime discovers the active ruleset version by reading a deterministic pointer file in object storage:

- Location (locked): `s3://{bucket}/rulesets/{environment}/{ruleset_key}/manifest.json`
- Purpose: map `(environment, ruleset_key)` → active `(ruleset_version, artifact_uri, checksum, published_at)`
- Runtime never lists storage to infer “latest”; it only reads this pointer.

Minimum required contents:
```json
{
  "schema_version": "1.0",
  "environment": "local",
  "ruleset_key": "CARD_AUTH",
  "ruleset_version": 42,
  "artifact_uri": "s3://fraud-gov-artifacts/rulesets/local/CARD_AUTH/v42/ruleset.json",
  "checksum": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "published_at": "2026-01-16T10:30:00Z"
}
```

**Note:** `schema_version` is optional for forward compatibility. Runtime implementations should ignore unknown fields.

## Doppler Configuration

### Local Environment

```bash
# Filesystem backend (simplest for local dev)
RULESET_ARTIFACT_BACKEND=filesystem

# OR MinIO backend (for S3-compatible testing)
RULESET_ARTIFACT_BACKEND=s3
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET_NAME=fraud-gov-artifacts
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_REGION=us-east-1
S3_FORCE_PATH_STYLE=true
```

### Test Environment

```bash
RULESET_ARTIFACT_BACKEND=s3
S3_ENDPOINT_URL=http://minio:9000  # Docker internal
S3_BUCKET_NAME=fraud-gov-artifacts
S3_ACCESS_KEY_ID=<from-doppler>
S3_SECRET_ACCESS_KEY=<from-doppler>
S3_REGION=us-east-1
S3_FORCE_PATH_STYLE=true
```

### Prod Environment

```bash
RULESET_ARTIFACT_BACKEND=s3
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_BUCKET_NAME=fraud-gov-artifacts-prod
S3_ACCESS_KEY_ID=<aws-iam-key>
S3_SECRET_ACCESS_KEY=<aws-iam-secret>
S3_REGION=us-east-1
S3_FORCE_PATH_STYLE=false
```

---

## MinIO Local Setup

### Start MinIO

```bash
# Start PostgreSQL + MinIO together
uv run db-local-up

# Or start only MinIO
docker compose -f docker-compose.local.yml up minio -d
```

### Access MinIO Console

- **URL**: http://localhost:9001
- **Username**: `minioadmin`
- **Password**: `minioadmin`

### Create Bucket (if needed)

The MinIO init container creates the bucket automatically. If you need to create it manually:

```bash
# Using MinIO client
docker exec -it fraud-gov-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec -it fraud-gov-minio mc mb local/fraud-gov-artifacts
```

---

## Testing

### Unit Tests

```bash
# Run all publisher tests (uses filesystem backend by default)
uv run pytest tests/test_unit_ruleset_publisher.py -v

# Run with coverage
uv run pytest tests/test_unit_ruleset_publisher.py --cov=app/services/ruleset_publisher --cov-report=html
```

### Integration Tests

```bash
# Test with filesystem backend
RULESET_ARTIFACT_BACKEND=filesystem uv run doppler-local-test

# Test with MinIO backend
RULESET_ARTIFACT_BACKEND=s3 uv run doppler-local-test
```

### Manual Testing

```bash
# 1. Start the API
uv run doppler-local

# 2. Create and approve a RuleSet
# (Use Swagger UI or API calls)

# 3. Check the artifact was published
ls .local/ruleset-artifacts/rulesets/dev/CARD_AUTH/
# OR
aws s3 ls s3://fraud-gov-artifacts/rulesets/dev/CARD_AUTH/ --endpoint-url http://localhost:9000

# 4. Check the runtime pointer (object storage)
aws s3 cp s3://fraud-gov-artifacts/rulesets/dev/CARD_AUTH/manifest.json - --endpoint-url http://localhost:9000

# 5. Check the governance audit record (DB)
psql $DATABASE_URL_APP -c "SELECT * FROM fraud_gov.ruleset_manifest ORDER BY created_at DESC LIMIT 5;"
```

---

## Error Handling

### Publishing Failures

If publishing fails, the approval transaction is rolled back:

```
User: Approve RuleSet
  ↓
System: Compile → Publish → Manifest
  ↓
Error: S3 connection timeout
  ↓
Result: RuleSet status NOT changed, no governance audit row, no artifact, no runtime pointer update
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `ValidationError: Rule type 'ALLOWLIST' cannot be published` | Attempting to publish ALLOWLIST/BLOCKLIST ruleset | Only AUTH and MONITORING rulesets can be published |
| `PublishingError: Failed to upload artifact` | S3/MinIO connection failure | Check S3_ENDPOINT_URL, credentials, network connectivity |
| `PublishingError: Checksum mismatch` | Artifact corruption | Retry approval, check storage backend |
| `IntegrityError: Unique constraint violation` | Race condition in version generation | Automatic retry (up to 3 attempts) |

---

## Determinism

### What Makes Artifacts Deterministic?

1. **Canonical JSON Serialization**
   - Keys sorted alphabetically
   - No extraneous whitespace
   - Consistent ordering of arrays and objects

2. **Rule Ordering**
   - Rules sorted by `priority DESC`, then `rule_id ASC`
   - Ensures same ruleset produces identical output

3. **Checksum Validation**
   - SHA-256 hash of canonical JSON bytes
   - 64-character hexadecimal string
   - Used to verify artifact integrity

### Verify Determinism

```bash
# Compile the same ruleset twice
# (Using the same input RuleSet)

# Compare checksums
digest1=$(jq -r '.' artifact1.json | sha256sum | cut -d' ' -f1)
digest2=$(jq -r '.' artifact2.json | sha256sum | cut -d' ' -f1)

if [ "$digest1" == "$digest2" ]; then
    echo "✅ Artifacts are identical"
else
    echo "❌ Artifacts differ"
fi
```

---

## Monitoring & Observability

### Metrics

The publisher service emits the following metrics:

- `ruleset_publish_duration_seconds` - Time to publish artifact
- `ruleset_publish_total{status="success|failure"}` - Publish outcome counter
- `ruleset_artifact_size_bytes` - Size of published artifact

### Logging

Publish operations are logged with:

```json
{
  "event": "ruleset_published",
  "ruleset_id": "uuid",
  "environment": "prod",
  "ruleset_key": "CARD_AUTH",
  "ruleset_version": 5,
  "artifact_uri": "s3://...",
  "checksum": "sha256:...",
  "duration_ms": 123,
  "created_by": "user@example.com"
}
```

---

## Troubleshooting

### Issue: "PublishingError: Failed to upload artifact"

**Symptoms:** Approval fails with publishing error

**Diagnosis:**
1. Check S3/MinIO is accessible: `curl http://localhost:9000/minio/health/ready`
2. Verify credentials in Doppler
3. Check bucket exists: `aws s3 ls s3://fraud-gov-artifacts --endpoint-url http://localhost:9000`

**Solution:**
- Ensure MinIO is running: `uv run db-local-up`
- Verify S3 credentials are correct
- Check network connectivity

### Issue: "ValidationError: Rule type cannot be published"

**Symptoms:** Approval fails with validation error

**Diagnosis:** Attempting to publish ALLOWLIST or BLOCKLIST ruleset

**Solution:**
- Only AUTH and MONITORING rulesets can be published
- ALLOWLIST/BLOCKLIST rules are compiled within AUTH context

### Issue: "IntegrityError: Unique constraint violation"

**Symptoms:** Approval fails with unique constraint error

**Diagnosis:** Race condition in version generation

**Solution:**
- Automatic retry (up to 3 attempts)
- If persists, check for concurrent approvals
- Verify database unique index exists

---

## Related Documentation

- **S3/MinIO Setup**: [docs/../01-setup/s3-setup.md](../01-setup/s3-setup.md)
- **Doppler Configuration**: [docs/05-deployment/doppler-secrets-setup.md](../05-deployment/doppler-secrets-setup.md)
- **API Reference**: [docs/03-api/reference.md](reference.md)
- **Implementation Guide**: [docs/07-reference.md](reference.md)
- **Clean Slate Reset**: [docs/../01-setup/clean-slate-reset.md](../01-setup/clean-slate-reset.md)

---

**Last Updated:** 2026-01-15
**Maintained By:** Development Team
