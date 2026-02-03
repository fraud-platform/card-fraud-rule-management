# Database Setup Guide

**This is the single source of truth for all database setup.** See [Neon API Reference](neon-api-reference.md) for API documentation or [Doppler Secrets Setup](../03-deployment/doppler-secrets-setup.md) for secrets management.

**PostgreSQL 18 with native UUIDv7 support**

**Need to delete everything and start fresh?** See [CLEAN_SLATE_RESET.md](CLEAN_SLATE_RESET.md) for complete reset instructions.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Database Architecture](#database-architecture)
3. [Password Workflow](#password-workflow-critical)
4. [Step-by-Step Setup](#step-by-step-setup)
5. [Repeatable Operations](#repeatable-operations)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

```powershell
# LOCAL DEVELOPMENT - ONE COMMAND DOES EVERYTHING
uv run local-full-setup --yes
# This command:
#   1. Checks Docker is running
#   2. Starts PostgreSQL 18 container (if not running)
#   3. Waits for database to be ready
#   4. Creates schema, users, indexes, seed data
#   5. Verifies setup

# Or with reset (deletes Docker volume first):
uv run local-full-setup --reset --yes

# NEON (test + prod) - ONE COMMAND DOES EVERYTHING
uv run neon-full-setup --yes
# This command:
#   1. Deletes existing Neon project (if any)
#   2. Creates new project with 'test' and 'prod' branches
#   3. Creates compute endpoints for each branch
#   4. Syncs DATABASE_URL_* to Doppler test/prod configs
#   5. Runs DDL, indexes, seed data on both databases
#   6. Verifies both databases

# Or setup specific environment only:
uv run neon-full-setup --config=test --yes   # Test branch only
uv run neon-full-setup --config=prod --yes   # Prod branch only

# Run tests to verify:
uv run doppler-test      # Tests against Neon 'test' branch
uv run doppler-prod      # Tests against Neon 'prod' branch
```

---

## Database Architecture

### Environment Mapping

| Environment | Database | Doppler Config | Setup Command |
|-------------|----------|----------------|---------------|
| **Local Dev** | Docker PostgreSQL 18 | `local` | `uv run local-full-setup --yes` |
| **Unit Tests** | Docker PostgreSQL 18 | `local` | `uv run local-full-setup --yes` |
| **CI/CD Tests** | Neon `test` branch | `test` | `uv run neon-full-setup --config=test --yes` |
| **Production** | Neon `prod` branch | `prod` | `uv run neon-full-setup --config=prod --yes` |

### Why Both Local and Neon?

**Local Docker Postgres:**
- 10-50ms faster per query (no network latency)
- Unlimited queries (no free tier limits)
- Safe for load testing (Locust, k6)
- Works offline
- Fully isolated per developer

**Neon Cloud:**
- Team-shared test data
- Branch-based isolation (test, production)
- Auto-backups with point-in-time recovery
- Matches production exactly
- Required for CI/CD

### Database Design

This system stores **rules as structured configuration objects**, not relational columns:

- **Relational tables**: Governance, lifecycle, audit, maker-checker
- **JSONB columns**: Rule conditions, velocity definitions, AST trees

| Aspect | Implementation |
|--------|----------------|
| **UUIDs** | UUIDv7 (generated in app, never in DB) |
| **Schema** | All tables in `fraud_gov` schema |
| **Driver** | psycopg v3 (NOT psycopg2) |
| **JSON Storage** | JSONB for condition trees |
| **Connection Pooling** | SQLAlchemy with pool_size=20, max_overflow=10 |
| **SSL Mode** | `require` (encrypts all traffic) |

### Core Tables (8 total)

| Table | Purpose |
|-------|---------|
| `rule_fields` | Defines allowed fields for rule conditions |
| `rule_field_metadata` | Extensible field metadata |
| `rules` | Logical rule identity |
| `rule_versions` | Actual rule content with JSONB condition_tree |
| `rulesets` | Deployment units with compiled AST |
| `ruleset_rules` | Junction: rulesets contain rule versions |
| `approvals` | Maker-checker workflow tracking |
| `audit_log` | Immutable audit trail |

### Roles vs Users

```
ROLES (no password, created by schema DDL)
 fraud_gov_app_role       CRUD on governance tables
 fraud_gov_analytics_role Read-only on specific tables
         |
         | GRANT role TO user
         v
USERS (with password, created by setup script)
 fraud_gov_app_user       LOGIN, member of app_role
 fraud_gov_analytics_user LOGIN, member of analytics_role
```

---

## Password Workflow (CRITICAL)

Each Doppler config (local, test, prod) has its **OWN UNIQUE passwords**. This is the single source of truth for how passwords work.

### The Golden Rule

> **DATABASE_URL_* in each Doppler config MUST use that environment's passwords.**
> Never copy passwords between environments.

### Password Sources

| Password | Source | Used By |
|----------|--------|---------|
| `FRAUD_GOV_APP_PASSWORD` | Set in Doppler (one-time) | `DATABASE_URL_APP` |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | Set in Doppler (one-time) | `DATABASE_URL_ANALYTICS` |
| `POSTGRES_ADMIN_PASSWORD` | Set in Doppler (local only) | Local `DATABASE_URL_ADMIN` |
| `neondb_owner` password | From Neon API (`reveal_password`) | Neon `DATABASE_URL_ADMIN` |

### Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1: Set passwords in Doppler (ONE-TIME, MANUAL)               │
│  ─────────────────────────────────────────────────────────────────  │
│  For EACH config (local, test, prod):                              │
│  - FRAUD_GOV_APP_PASSWORD (unique per environment)                 │
│  - FRAUD_GOV_ANALYTICS_PASSWORD (unique per environment)           │
│  - local only: POSTGRES_ADMIN_PASSWORD                             │
└─────────────────────────────────────────────────────────────────────┘
                              |
                              v
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2: Run neon-setup (gets hosts from Neon API)                 │
│  ─────────────────────────────────────────────────────────────────  │
│  Output: endpoint hosts + neondb_owner password                    │
│  DATABASE_URL_* uses PLACEHOLDERS for app/analytics passwords      │
└─────────────────────────────────────────────────────────────────────┘
                              |
                              v
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3: Sync Doppler connection strings (AUTOMATED)              │
│  ─────────────────────────────────────────────────────────────────  │
│  For EACH environment (test, prod):                                │
│  1. Reads Neon endpoint hosts (test + production)                  │
│  2. Reads FRAUD_GOV_*_PASSWORD from THAT Doppler config            │
│  3. Writes DATABASE_URL_* into Doppler                             │
└─────────────────────────────────────────────────────────────────────┘
                              |
                              v
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 4: Run setup_database.py init (creates users)                │
│  ─────────────────────────────────────────────────────────────────  │
│  Uses --password-env flag to read from CURRENT Doppler config       │
│  Creates fraud_gov_app_user with FRAUD_GOV_APP_PASSWORD            │
│  Creates fraud_gov_analytics_user with FRAUD_GOV_ANALYTICS_PASSWORD│
└─────────────────────────────────────────────────────────────────────┘
```

### Example: Correct Workflow

```powershell
# Step 1: Set passwords in Doppler (do this once per environment)
doppler secrets --project=card-fraud-rule-management --config=test set FRAUD_GOV_APP_PASSWORD "<generate-unique-password>"
doppler secrets --project=card-fraud-rule-management --config=test set FRAUD_GOV_ANALYTICS_PASSWORD "<generate-unique-password>"

# Step 2: Run neon-setup (outputs placeholders)
uv run neon-setup --yes --create-compute
# Output shows: DATABASE_URL_APP=postgresql://...:{FRAUD_GOV_APP_PASSWORD}@...

# Step 3: Sync DATABASE_URL_* into Doppler (writes to test + prod)
uv run db-sync-doppler-urls --yes

# Step 4: Initialize database (uses Doppler `test`)
uv run db-init-test
```

---

## Step-by-Step Setup

### Prerequisites

- **Docker Desktop** (for local PostgreSQL)
- **Doppler CLI** installed and authenticated
- **Neon account** with organization API key

### Step 1: Generate Secure Passwords (One-Time)

```powershell
# Generate strong passwords (16+ chars)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 2: Add Secrets to Doppler (One-Time, Manual)

Add these to **all Doppler configs** (`local`, `test`, `prod`):

| Secret | Local | Test | Prod | Purpose |
|--------|-------|------|------|---------|
| `FRAUD_GOV_APP_PASSWORD` | ✅ | ✅ | ✅ | App user password |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | ✅ | ✅ | ✅ | Analytics user password |
| `NEON_API_KEY` | ✅ | ❌ | ❌ | Neon API key (local only) |
| `POSTGRES_ADMIN_PASSWORD` | ✅ | ❌ | ❌ | Local Docker admin only |

**Get Neon API Key:** https://console.neon.tech/app/settings/api-keys
- Use an **Organization API key** (not personal)

### Step 3: Set Up Local Docker (Local Dev)

```powershell
# One command does everything
uv run local-full-setup --yes

# Or with reset (deletes Docker volume first)
uv run local-full-setup --reset --yes
```

**What this does:**
1. Checks Docker is running
2. Starts PostgreSQL 18 container
3. Waits for database to be ready
4. Creates users with passwords from Doppler 'local' config
5. Creates schema, indexes, seed data
6. Verifies setup

**Expected output:**
```
[OK] Users: Found: fraud_gov_analytics_user, fraud_gov_app_user
[OK] Schema: Found 9 tables
[OK] Indexes: Found 48 indexes
[OK] Seed data: Found 8 rule fields
```

### Step 4: Set Up Neon Project (One Command)

The recommended approach is to use `neon-full-setup` which handles everything:

```powershell
# Full automated setup: delete/create project, branches, sync Doppler, init DBs
uv run neon-full-setup --yes
```

**What this does:**
1. Deletes existing Neon project (if any)
2. Creates Neon project `fraud-governance` (PostgreSQL 18)
3. Creates `test` branch with compute endpoint
4. Creates `prod` branch with compute endpoint
5. Syncs `DATABASE_URL_*` to Doppler `test` and `prod` configs
6. Runs DDL, indexes, seed data on both databases
7. Verifies both databases

**Setup specific environment only:**
```powershell
uv run neon-full-setup --config=test --yes   # Test branch only
uv run neon-full-setup --config=prod --yes   # Prod branch only
```

**Granular commands (if you need step-by-step control):**
```powershell
# Step 4a: Create project and branches
uv run neon-setup --yes --create-compute

# Step 4b: Sync DATABASE_URL_* to Doppler
uv run db-sync-doppler-urls --yes

# Step 4c: Initialize databases
uv run db-init-test    # Test branch
uv run db-init-prod    # Prod branch

# Step 4d: Verify
uv run db-verify-test
uv run db-verify-prod
```

---

## Repeatable Operations

### Database Reset (Data Only - Fast)

**Use for:** Cleaning test data without dropping schema

```powershell
# Local
uv run db-reset-data-local

# Test (Neon)
uv run db-reset-data-test

# Prod (Neon)
uv run db-reset-data-prod
```

**What happens:**
- Truncates all 8 tables (FK-safe order)
- Reseeds `rule_fields` (8 rows)
- Preserves schema, indexes, users

### Database Reset (Full Schema - Destructive)

**Use for:** Complete reset including schema changes

```powershell
# Local
uv run db-reset-schema-local

# Test (Neon)
uv run db-reset-schema-test

# Prod (prompts unless you pass `--yes`)
uv run db-reset-schema-prod
```

**What happens:**
- Drops `fraud_gov` schema
- Recreates schema, enums, tables
- Applies indexes (43 indexes)
- Reseeds data

### Seed Demo Data

```powershell
# Local
uv run db-seed-demo

# Test
doppler run --config test -- uv run python scripts/setup_database.py seed --demo --password-env --yes
```

### Verify Setup

```powershell
# Local
uv run db-verify-local

# Test
uv run db-verify-test

# Prod
uv run db-verify-prod
```

---

## Command Reference

### Database Setup Commands

| Command | Description |
|---------|-------------|
| `uv run db-init-local` | First-time setup (local Docker) |
| `uv run db-init-test` | First-time setup (Neon test) |
| `uv run db-init-prod` | First-time setup (Neon prod) |
| `uv run db-reset-schema-local` | Drop and recreate schema (local) |
| `uv run db-reset-data-local` | Truncate tables, reseed data (local) |
| `uv run db-reset-schema-test` | Drop/recreate schema (Neon test) |
| `uv run db-reset-data-test` | Truncate data (Neon test) |
| `uv run db-reset-schema-prod` | Drop/recreate schema (Neon prod) |
| `uv run db-reset-data-prod` | Truncate data (Neon prod) |
| `uv run db-seed-demo` | Apply demo data (local) |
| `uv run db-verify-local` | Verify setup (local) |
| `uv run db-verify-test` | Verify setup (Neon test) |
| `uv run db-verify-prod` | Verify setup (Neon prod) |

### Local Commands

| Command | Description |
|---------|-------------|
| `uv run local-full-setup --yes` | **RECOMMENDED** Full local setup: Docker, init, verify |
| `uv run local-full-setup --reset --yes` | Reset Docker volume and setup fresh |
| `uv run db-local-up` | Start PostgreSQL container only |
| `uv run db-local-down` | Stop PostgreSQL container |
| `uv run db-local-reset` | Delete Docker volume |

### Neon Commands

| Command | Description |
|---------|-------------|
| `uv run neon-full-setup --yes` | **RECOMMENDED** Full setup: delete/create project, branches, sync Doppler, init DBs |
| `uv run neon-full-setup --config=test --yes` | Full setup for test branch only |
| `uv run neon-full-setup --config=prod --yes` | Full setup for prod branch only |
| `uv run neon-setup --yes --create-compute` | Create project, branches, and compute endpoints (granular) |
| `uv run neon-setup --delete-project --yes` | Delete entire Neon project |
| `uv run db-sync-doppler-urls --yes` | Sync DATABASE_URL_* to Doppler test/prod configs |

---

## Troubleshooting

### Issue: "password authentication failed for user 'postgres'"

**Cause:** Volume was initialized with different password

**Fix:**
```powershell
# Reset volume
docker compose -f docker-compose.local.yml down -v

# Restart with Doppler (injects correct password)
doppler run --config local -- docker compose -f docker-compose.local.yml up -d
```

### Issue: Neon endpoints not ready

**Cause:** Compute takes time to provision

**Fix:** Wait 30-60 seconds after neon-setup, then verify connection strings are correct in Doppler.

### Issue: "relation does not exist"

**Cause:** `search_path` doesn't include `fraud_gov`

**Fix:** Schema-qualify table names:
```sql
SELECT * FROM fraud_gov.rules;
```

Or run `uv run db-init` to set up schema.

### Issue: Password authentication failed for fraud_gov_app_user

**Cause:** DATABASE_URL_APP password doesn't match the actual user password in database

**Fix:**
1. Verify passwords match in Doppler config
2. Re-run `setup_database.py --password-env init` to recreate users with correct passwords
3. Remember: each environment (local, test, prod) has unique passwords

### Issue: Neon branch has no compute

**Fix via Console:**
1. Go to: https://console.neon.tech
2. Select project: `fraud-governance`
3. Select branch: `test` or `prod`
4. Click "Add compute" → Select "Plan" (free tier, scales to zero)

**Or via API:**
```powershell
uv run neon-setup --create-compute --yes
```

---

## Connection String Formats

### Local Docker

```
DATABASE_URL_ADMIN=postgresql://postgres:${POSTGRES_ADMIN_PASSWORD}@localhost:5432/fraud_gov
DATABASE_URL_APP=postgresql://fraud_gov_app_user:${FRAUD_GOV_APP_PASSWORD}@localhost:5432/fraud_gov
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:${FRAUD_GOV_ANALYTICS_PASSWORD}@localhost:5432/fraud_gov
```

### Neon (test/prod branches)

```
DATABASE_URL_ADMIN=postgresql://neondb_owner:<npg_password>@<host>.neon.tech/neondb?sslmode=require
DATABASE_URL_APP=postgresql://fraud_gov_app_user:${FRAUD_GOV_APP_PASSWORD}@<host>.neon.tech/neondb?sslmode=require
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:${FRAUD_GOV_ANALYTICS_PASSWORD}@<host>.neon.tech/neondb?sslmode=require
```

---

## SQL Files Reference

| File | Purpose |
|------|---------|
| `db/fraud_governance_schema.sql` | Main DDL (types, tables, RLS, roles) |
| `db/production_indexes.sql` | Performance indexes (43 indexes) |
| `db/seed_rule_fields.sql` | Core seed data (8 rule fields) |
| `db/local_setup.sql` | Local Docker user setup |
| `db/create_users.sql` | Manual user creation (reference only) |

---

## Next Steps

After database setup:

1. **Complete Auth0 Setup**: See [auth0-setup.md](auth0-setup.md)
2. **Verify Complete Setup**: See [verification.md](verification.md)
3. **Start Development**: See [../02-development/workflow.md](../02-development/workflow.md)

---

## Additional Resources

- **Neon API Reference**: [neon-api-reference.md](neon-api-reference.md)
- **Doppler Secrets**: [../03-deployment/doppler-secrets-setup.md](../03-deployment/doppler-secrets-setup.md)
- **Neon Documentation**: https://neon.tech/docs
- **PostgreSQL Documentation**: https://www.postgresql.org/docs
- **psycopg v3 Documentation**: https://www.psycopg.org/psycopg3/

---

**Last Updated**: 2026-01-17
