# S3 / MinIO Setup (Ruleset Artifact Publishing)

This guide covers setting up **S3-compatible object storage** for the governance API’s **ruleset artifact publishing**.

It is designed for:
- **Local development** using **MinIO** (S3-compatible)
- **Cloud environments** using **AWS S3** (or any S3-compatible provider)

> Repo note: Secrets are managed via **Doppler** (preferred). Avoid `.env` files.

---

## What this storage is for

When the system approves a **ruleset**, the service will:
1. Compile the full ruleset to deterministic JSON
2. Upload the JSON artifact to S3-compatible storage
3. Record a manifest row in Postgres pointing to the artifact URI + checksum

Publishing is **not a user action**, and must be **atomic** with approval.

---

## Required configuration (Doppler)

Add these to the relevant Doppler config (`local`, `test`, `prod`).

### Common
- `RULESET_ARTIFACT_BACKEND`: `s3` (for S3/MinIO) or `filesystem` (for local-only testing)

### S3 / MinIO
- `S3_BUCKET_NAME`: bucket to store artifacts (example: `fraud-gov-artifacts`)
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_REGION`: region name (MinIO accepts any; AWS requires correct region)

Optional but commonly needed:
- `S3_ENDPOINT_URL`: required for MinIO (example: `http://localhost:9000`), typically omitted for AWS
- `S3_FORCE_PATH_STYLE`: `true` for many MinIO setups
- `RULESET_ARTIFACT_PREFIX`: example `fraud-gov/{ENV}/{RULESET_KEY}/`

Locked decision: `{RULESET_KEY}` is one of:
- `CARD_AUTH`
- `CARD_MONITORING`

---

## Local setup: MinIO (Windows + Docker)

### Quick Start (Recommended)

This repository includes **fully automated MinIO setup** via Docker Compose + uv scripts:

```powershell
# Start MinIO with Doppler secrets (auto-creates bucket)
uv run objstore-local-up

# Or start both PostgreSQL + MinIO together
uv run infra-local-up

# Verify MinIO is working
uv run objstore-local-verify

# Stop MinIO when done
uv run objstore-local-down

# Reset MinIO (delete all data)
uv run objstore-local-reset
```

### What's Automated

The automation includes:
- ✅ **Docker Compose services** (MinIO + init container)
- ✅ **Auto-created bucket** (`fraud-gov-artifacts`) via `minio/mc` init container
- ✅ **Doppler integration** for credentials
- ✅ **Health checks** for container readiness
- ✅ **Verify command** to test connectivity and list buckets

### Manual Setup (If Needed)

If you prefer manual setup or need to understand what's automated:

#### FAQ / clarity

**Do I need to create a MinIO account?**
No. For local development we run MinIO as a Docker container. There is no external MinIO "account".

**Do I need to share an API key?**
No. The "API key" is just the access key + secret configured for your local MinIO container.
Keep these values in Doppler `local` only.

**What can be fully automated vs what stays manual?**
- ✅ **Automated** (via `uv run objstore-local-up`): Docker Compose services + bucket creation via `minio/mc` init container
- **Manual** (one-time): Set Doppler `local` secrets (agents can document exact names/values, but you apply them in Doppler)

#### Manual MinIO Setup (Alternative)

**Step 1: Start MinIO**

```powershell
# Choose credentials (store these in Doppler local config)
$env:MINIO_ROOT_USER = "minioadmin"
$env:MINIO_ROOT_PASSWORD = "minioadmin"

docker run --name fraud-gov-minio -d `
  -p 9000:9000 -p 9001:9001 `
  -e MINIO_ROOT_USER=$env:MINIO_ROOT_USER `
  -e MINIO_ROOT_PASSWORD=$env:MINIO_ROOT_PASSWORD `
  minio/minio server /data --console-address ":9001"
```

- S3 API endpoint: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

**Step 2: Create a bucket**

Option A: MinIO client (`mc`) container (no local install required)

```powershell
$bucket = "fraud-gov-artifacts"

docker run --rm --network host minio/mc `
  alias set local http://localhost:9000 $env:MINIO_ROOT_USER $env:MINIO_ROOT_PASSWORD

docker run --rm --network host minio/mc `
  mb --ignore-existing local/$bucket
```

Option B: AWS CLI (works with MinIO too)

```powershell
$bucket = "fraud-gov-artifacts"
aws --endpoint-url http://localhost:9000 s3 mb s3://$bucket
```

**Step 3: Wire into Doppler `local` config**

Set:
- `S3_ENDPOINT_URL=http://localhost:9000`
- `S3_BUCKET_NAME=fraud-gov-artifacts`
- `S3_ACCESS_KEY_ID=minioadmin`
- `S3_SECRET_ACCESS_KEY=minioadmin`
- `S3_REGION=us-east-1`
- `S3_FORCE_PATH_STYLE=true`

---

## Cloud setup: AWS S3

### 1) Create bucket

- Create a bucket (example: `fraud-gov-artifacts`) in your target AWS account.
- Choose region (example: `us-east-1`).

### 2) IAM policy (minimum)

Grant the governance service identity permissions to:
- `s3:PutObject`
- `s3:GetObject`
- `s3:ListBucket`

Restrict to a prefix if you use one (recommended).

### 3) Doppler config

Set (per environment):
- `S3_BUCKET_NAME`
- `S3_REGION`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`

Typically omit `S3_ENDPOINT_URL` for AWS.

---

## Quick verification (works for MinIO)

With AWS CLI:

```powershell
# List buckets
aws --endpoint-url http://localhost:9000 s3 ls

# List objects (after publishing starts writing artifacts)
aws --endpoint-url http://localhost:9000 s3 ls s3://fraud-gov-artifacts --recursive
```

---

## Troubleshooting

### “SignatureDoesNotMatch” / auth errors
- Confirm `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`
- For MinIO: set `S3_ENDPOINT_URL` and `S3_FORCE_PATH_STYLE=true`

### Connection refused
- Confirm container is running: `docker ps`
- Check ports 9000/9001 are free

### Bucket not found
- Create bucket first (see steps above)

---

## Related docs

- Database reset workflow: [docs/01-setup/clean-slate-reset.md](clean-slate-reset.md)
- Database setup (canonical): [docs/01-setup/database-setup.md](database-setup.md)
- AGENTS.md - Complete command reference for AI agents and developers
