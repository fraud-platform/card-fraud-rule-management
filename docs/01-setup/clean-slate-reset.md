# Clean Slate Reset - Delete Everything and Start Fresh

**Purpose:** Complete reset of ALL databases (Local Docker, Neon Test, Neon Production).

**When to use:**
- Database schema changes (e.g., added `version` column)
- Corrupted data or schema
- Starting fresh on a new machine
- Coding agents setting up from scratch

**What this does:**
1. Deletes local Docker database and volumes
2. Deletes entire Neon project (all branches, all data)
3. Recreates Neon project with test/production branches + compute
4. Initializes all databases with fresh schema

---

## Quick command map (new users + coding agents)

You only need **one** test command per environment:

| What you want | Command |
|---|---|
| Run API locally (uses Doppler `local` config) | `uv run doppler-local` |
| Run tests against local Docker DB (uses Doppler `local` config) | `uv run doppler-local-test` |
| Run tests against Neon test branch (uses Doppler `test` config) | `uv run doppler-test` |
| Run tests against Neon production branch DB URLs (uses Doppler `prod` config) | `uv run doppler-prod` |

Notes:
- `doppler-local` runs the FastAPI dev server.
- `doppler-local-test` runs pytest against the **local Docker** database.
- `doppler-test` / `doppler-prod` run pytest against Neon endpoints.

---

## Prerequisites

Verify these exist in Doppler (should already be set):

```powershell
# If any of these are missing, the automation commands will fail with a clear error:
# - NEON_API_KEY (in Doppler `local` config)
# - FRAUD_GOV_APP_PASSWORD, FRAUD_GOV_ANALYTICS_PASSWORD (in Doppler `test` + `prod` configs)
# - Doppler access/token configured locally
```

---

## Complete Reset Workflow

### Step 1: Delete Local Docker Database

```powershell
# Stop and delete everything (including volumes)
uv run db-local-reset
```

### Step 2: Delete Neon Project

```powershell
# Deletes entire project (ALL data will be lost)
uv run neon-setup --delete-project --yes
```

**Expected output:**
```
[OK] Found project 'fraud-governance' (ID: xxx)
[OK] Project deleted: fraud-governance
```

### Step 3: Recreate Neon Project with Compute

```powershell
# Creates project + branches + compute endpoints
uv run neon-setup --yes --create-compute
```

**Expected output:**
```
[OK] Project created: fraud-governance
[OK] Branch created: test
[OK] Compute endpoint created
[OK] Branch created: production
[OK] Compute endpoint created

TEST BRANCH - Copy to Doppler 'test' config:
DATABASE_URL_ADMIN=postgresql://neondb_owner:npg_xxx@ep-test-xxx.../neondb?sslmode=require
DATABASE_URL_APP=postgresql://fraud_gov_app_user:{FRAUD_GOV_APP_PASSWORD}@ep-test-xxx.../neondb?sslmode=require
...

PRODUCTION BRANCH - Copy to Doppler 'prod' config:
DATABASE_URL_ADMIN=postgresql://neondb_owner:npg_yyy@ep-prod-xxx.../neondb?sslmode=require
DATABASE_URL_APP=postgresql://fraud_gov_app_user:{FRAUD_GOV_APP_PASSWORD}@ep-prod-xxx.../neondb?sslmode=require
...
```

**Save the output** - you'll need the hostnames for next step.

### Step 4: Update Doppler Connection Strings

This is automated and does not print secrets:

```powershell
# Sync DATABASE_URL_ADMIN/APP/ANALYTICS in Doppler `test` and `prod` configs based on Neon endpoints.
# (Uses NEON_API_KEY from Doppler `local` config.)
uv run db-sync-doppler-urls --yes
```

If your Neon endpoints don’t exist yet, re-run with compute creation:

```powershell
uv run db-sync-doppler-urls --yes --create-compute
```

### Step 5: Start Local Docker Database

```powershell
# Start PostgreSQL with Doppler secrets
uv run db-local-up

# Wait for it to be healthy
docker exec fraud-gov-postgres pg_isready -U postgres
```

### Step 6: Initialize All Databases

```powershell
# Local database
uv run db-init

# Neon test database
uv run db-init-test

# Neon production database
uv run db-init-prod
```

**Expected output for each:**
```
[OK] Users: Found: fraud_gov_analytics_user, fraud_gov_app_user
[OK] Schema: Found 9 tables (including ruleset_manifest for artifact publishing)
[OK] Indexes: Found 46 indexes
[OK] Seed data: Found 8 rule fields

Database setup completed successfully!
```

### Step 7: Verify Everything Works

```powershell
# Test against local database
uv run doppler-local-test

# Test against Neon test database
uv run doppler-test
```

Both should show ~300+ tests passing.

---

## Note: Object storage for ruleset artifacts

If you are working on (or testing) **ruleset artifact publishing** (S3-compatible storage), you may also need a local MinIO container.

MinIO is local-only infrastructure (Docker). It does not require creating any external account.

See: [docs/../01-setup/s3-setup.md](s3-setup.md)

---

## Quick Reference Commands

| Task | Command |
|------|---------|
| Delete local DB | `docker compose -f docker-compose.local.yml down -v` |
| Start local DB | `doppler run --config local -- docker compose -f docker-compose.local.yml up -d` |
| Delete Neon project | `doppler run -- uv run python scripts/setup_neon.py --delete-project --yes` |
| Create Neon project | `doppler run -- uv run python scripts/setup_neon.py --yes --create-compute` |
| Init local DB | `uv run db-init` |
| Init test DB | `uv run db-init-test` |
| Init prod DB | `uv run db-init-prod` |
| Test local | `uv run doppler-local-test` |
| Test Neon | `uv run doppler-test` |

---

## Common Issues

### Issue: "port 5432 already allocated"

**Cause:** Another PostgreSQL container is running.

**Fix:**
```powershell
docker ps -a | findstr "5432"
docker stop <container_id>
docker rm <container_id>
```

### Issue: "password authentication failed"

**Cause:** Doppler connection string password doesn't match database user password.

**Fix:**
1. Verify DATABASE_URL_* passwords match FRAUD_GOV_*_PASSWORD in Doppler config
2. Re-run `uv run db-init` to recreate users with correct passwords
3. Remember: each environment (local, test, prod) has unique passwords from Doppler

### Issue: Neon endpoint not ready

**Cause:** Compute takes 30-60 seconds to provision.

**Fix:** Wait and retry. The `--create-compute` flag waits automatically.

---

## Key Concepts

### Password Isolation

Each environment has **different** passwords for the same user:

| User | Local | Test | Prod |
|------|-------|------|------|
| `fraud_gov_app_user` | `<from local config>` | `<from test config>` | `<from prod config>` |
| `fraud_gov_analytics_user` | `<from local config>` | `<from test config>` | `<from prod config>` |

**Never copy passwords between environments!** All passwords come from Doppler config.

### Doppler Config Usage

| Config | Used For | Database |
|--------|----------|----------|
| `local` | Local dev/testing | Docker localhost:5432 |
| `test` | CI/CD testing | Neon test branch |
| `prod` | Production | Neon production branch |

### Command Argument Order (CRITICAL)

**CORRECT:**
```powershell
scripts/setup_database.py --password-env --yes init
```

**WRONG:**
```powershell
scripts/setup_database.py init --password-env --yes  # ❌ Will fail!
```

The `--password-env` and `--yes` flags must come **BEFORE** the subcommand (`init`).

---

**Last Updated:** 2026-01-13
