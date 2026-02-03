# Database Setup - Complete Repeatable Guide

> **DEPRECATED: This file has been superseded.**
>
> **Please use [database-setup.md](database-setup.md) as the single source of truth for all database setup.**
>
> This file is kept for historical reference only and may be removed in the future.

---

This guide provides a **repeatable, step-by-step process** for setting up the PostgreSQL 18 database for the Fraud Rule Governance API across all environments (local, test, production).

**PostgreSQL 18 with native UUIDv7 support**

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [One-Time Setup](#one-time-setup)
3. [Environment-Specific Setup](#environment-specific-setup)
4. [Manual vs Automated Steps](#manual-vs-automated-steps)
5. [Repeatable Operations](#repeatable-operations)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

```powershell
# 1. One-time: Add secrets to Doppler (MANUAL)
# 2. One-time: Set up Neon project/branches (AUTOMATED)
uv run neon-setup --create-compute --yes

# 3. One-time per environment: Initialize database (AUTOMATED)
uv run db-init-test      # Test environment (Neon)
uv run db-init-prod      # Production environment (Neon)

# 4. Repeatable: Verify setup (AUTOMATED)
uv run db-verify
```

---

## One-Time Setup (Do Once)

### Step 1: Generate Secure Passwords

Generate strong passwords for database users:

```powershell
# Generate two passwords (16+ chars, mix of upper/lower/numbers/symbols)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 2: Add Secrets to Doppler (MANUAL)

Add these secrets to **all Doppler configs** (`local`, `test`, `prod`):

| Secret | Local | Test | Prod | Purpose |
|--------|-------|------|------|---------|
| `FRAUD_GOV_APP_PASSWORD` | ✅ | ✅ | ✅ | App user password |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | ✅ | ✅ | ✅ | Analytics user password |
| `NEON_API_KEY` | ✅ | ❌ | ❌ | Neon API key (local only) |
| `POSTGRES_ADMIN_PASSWORD` | ✅ | ❌ | ❌ | Local Docker admin only |

**Get Neon API Key:** https://console.neon.tech/app/settings/api-keys
- Use an **Organization API key** (not personal) for admin access

### Step 3: Set Up Local Docker (AUTOMATED)

```powershell
# Start local PostgreSQL 18
uv run db-local-up

# Initialize database (creates schema, users, indexes, seed data)
uv run db-init

# Verify setup
uv run db-verify
```

---

## Environment-Specific Setup

### Local Development (Docker PostgreSQL 18)

```powershell
# Start database
uv run db-local-up

# Initialize (first time only)
uv run db-init

# Verify
uv run db-verify
```

**Connection strings for Doppler `local` config:**
```
DATABASE_URL_ADMIN=postgresql://postgres:${POSTGRES_ADMIN_PASSWORD}@localhost:5432/fraud_gov
DATABASE_URL_APP=postgresql://fraud_gov_app_user:${FRAUD_GOV_APP_PASSWORD}@localhost:5432/fraud_gov
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:${FRAUD_GOV_ANALYTICS_PASSWORD}@localhost:5432/fraud_gov
```

### Neon Test Branch

```powershell
# 1. Create Neon project and branches (ONE-TIME)
uv run neon-setup --yes --create-compute

# 2. Sync DATABASE_URL_* into Doppler (writes test + prod)
uv run db-sync-doppler-urls --yes

# 3. Initialize test database
uv run db-init-test

# 4. Verify
uv run db-verify
```

### Neon Production Branch

```powershell
# 1. Project already created by neon-setup

# 2. Sync DATABASE_URL_* into Doppler (writes test + prod)
uv run db-sync-doppler-urls --yes

# 3. Initialize production database
uv run db-init-prod

# 4. Verify
uv run db-verify-prod
```

---

## Manual vs Automated Steps

### Automated (Scripted) Steps

| Step | Script | Run Frequency |
|------|--------|---------------|
| Create Neon project/branches | `uv run neon-setup` | One-time |
| Create database users | `uv run db-init` | One-time per environment |
| Create schema/tables/indexes | `uv run db-init` | One-time per environment |
| Seed data | `uv run db-init` | One-time per environment |
| Reset schema (drop/recreate) | `uv run db-reset-schema` | As needed |
| Reset data (truncate only) | `uv run db-reset-data` | As needed |
| Verify setup | `uv run db-verify` | Any time |

### Manual (One-Time) Steps

| Step | How |
|------|-----|
| Generate passwords | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| Add secrets to Doppler | Via Doppler Dashboard or CLI |
| Get Neon API key | https://console.neon.tech/app/settings/api-keys |
| Sync connection strings to Doppler | `uv run db-sync-doppler-urls --yes` |

---

## Repeatable Operations

### Database Reset (Data Only - Fast)

**Use for:** Cleaning test data without dropping schema

```powershell
# Local
uv run db-reset-data

# Test (Neon)
uv run db-reset-data-test

# Production (if needed)
uv run db-reset-data-prod
```

**What happens:**
- Truncates all 10 tables (FK-safe order)
- Reseeds `rule_fields` (8 rows)
- Preserves schema, indexes, users

### Database Reset (Full Schema - Destructive)

**Use for:** Complete reset including schema changes

```powershell
# Local
uv run db-reset-schema

# Test (Neon)
uv run db-reset-schema-test

# Production (prompts unless you pass `--yes`)
uv run db-reset-schema-prod
```

**What happens:**
- Drops `fraud_gov` schema
- Recreates schema, enums, tables
- Applies indexes (43 indexes)
- Reseeds data

### Seed Demo Data

**Use for:** Adding sample rulesets and rules for testing

```powershell
# Local
uv run db-seed-demo

# Test
doppler run --config test -- uv run python scripts/setup_database.py --password-env --yes seed --demo
```

---

## Command Reference

### Database Setup Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `uv run db-init` | `db-init` | First-time setup (local) |
| `uv run db-init-test` | `db-init-test` | First-time setup (Neon test) |
| `uv run db-init-prod` | `db-init-prod` | First-time setup (Neon prod) |
| `uv run db-reset-schema` | `db-reset-schema` | Drop and recreate schema (local) |
| `uv run db-reset-data` | `db-reset-data` | Truncate tables, reseed data (local) |
| `uv run db-reset-schema-test` | `db-reset-schema-test` | Drop/recreate schema (Neon test) |
| `uv run db-reset-data-test` | `db-reset-data-test` | Truncate data (Neon test) |
| `uv run db-reset-schema-prod` | `db-reset-schema-prod` | Drop/recreate schema (Neon prod) |
| `uv run db-reset-data-prod` | `db-reset-data-prod` | Truncate data (Neon prod) |
| `uv run db-seed-demo` | `db-seed-demo` | Apply demo data (local) |
| `uv run db-verify` | `db-verify` | Verify setup (local) |
| `uv run db-verify-test` | `db-verify-test` | Verify setup (Neon test) |
| `uv run db-verify-prod` | `db-verify-prod` | Verify setup (Neon prod) |
| `scripts/setup_database.py create-users` | - | Create users only |

### Neon Commands

| Command | Description |
|---------|-------------|
| `uv run neon-setup --yes --create-compute` | Create project, branches, and compute endpoints |
| `uv run neon-setup --delete-project --yes` | Delete entire Neon project |
| `uv run python scripts/fetch_neon_connections.py` | Inspect connection strings (read-only; no Doppler writes) |
| `uv run db-sync-doppler-urls --yes` | Write `DATABASE_URL_*` into Doppler for test + prod |

### Local Docker Commands

| Command | Description |
|---------|-------------|
| `uv run db-local-up` | Start PostgreSQL 18 in Docker |
| `uv run db-local-down` | Stop database |
| `uv run db-local-reset` | Delete volume and data |

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

**Fix:** Wait 30-60 seconds, then run:
```powershell
uv run python scripts/fetch_neon_connections.py
```

Or re-run the sync (writes URLs into Doppler):
```powershell
uv run db-sync-doppler-urls --yes
```

### Issue: "relation does not exist"

**Cause:** `search_path` doesn't include `fraud_gov`

**Fix:** Schema-qualify table names:
```sql
SELECT * FROM fraud_gov.rules;
```

Or run `uv run db-init` to set up schema.

### Issue: Neon branch has no compute

**Fix via Console:**
1. Go to: https://console.neon.tech
2. Select project: `fraud-governance`
3. Select branch: `test` or `production`
4. Click "Add compute" → Select "Plan" (free tier, scales to zero)

**Or via API (automated):**
```powershell
uv run neon-setup --create-compute --yes
```

---

## Doppler Secrets Reference

### Local Environment (`local`)

```bash
# Application Config
APP_ENV=local
APP_REGION=india

# Database Connection Strings
DATABASE_URL_ADMIN=postgresql://postgres:${POSTGRES_ADMIN_PASSWORD}@localhost:5432/fraud_gov
DATABASE_URL_APP=postgresql://fraud_gov_app_user:${FRAUD_GOV_APP_PASSWORD}@localhost:5432/fraud_gov
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:${FRAUD_GOV_ANALYTICS_PASSWORD}@localhost:5432/fraud_gov

# Database User Passwords
POSTGRES_ADMIN_PASSWORD=<strong-password>
FRAUD_GOV_APP_PASSWORD=<strong-password>
FRAUD_GOV_ANALYTICS_PASSWORD=<strong-password>

# Neon API Key
NEON_API_KEY=<your-neon-api-key>
```

### Test Environment (`test`)

```bash
# Application Config
APP_ENV=test
APP_REGION=india

# Database Connection Strings (Neon test branch)
DATABASE_URL_ADMIN=postgresql://neondb_owner:{NEON_DB_OWNER_PASSWORD}@<host>.neon.tech/neondb?sslmode=require
DATABASE_URL_APP=postgresql://fraud_gov_app_user:${FRAUD_GOV_APP_PASSWORD}@<host>.neon.tech/neondb?sslmode=require
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:${FRAUD_GOV_ANALYTICS_PASSWORD}@<host>.neon.tech/neondb?sslmode=require

# Database User Passwords
FRAUD_GOV_APP_PASSWORD=<strong-password>
FRAUD_GOV_ANALYTICS_PASSWORD=<strong-password>
```

### Production Environment (`prod`)

```bash
# Application Config
APP_ENV=production
APP_REGION=india

# Database Connection Strings (Neon production branch)
DATABASE_URL_ADMIN=postgresql://neondb_owner:{NEON_DB_OWNER_PASSWORD}@<host>.neon.tech/neondb?sslmode=require
DATABASE_URL_APP=postgresql://fraud_gov_app_user:${FRAUD_GOV_APP_PASSWORD}@<host>.neon.tech/neondb?sslmode=require
DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:${FRAUD_GOV_ANALYTICS_PASSWORD}@<host>.neon.tech/neondb?sslmode=require

# Database User Passwords
FRAUD_GOV_APP_PASSWORD=<strong-password>
FRAUD_GOV_ANALYTICS_PASSWORD=<strong-password>
```

---

## Architecture Summary

### Roles vs Users

```
┌─────────────────────────────────────────────────────────────────┐
│  ROLES (no password, created by schema DDL)                     │
│  ─────────────────────────────────────────                      │
│  fraud_gov_app_role       → CRUD on governance tables           │
│  fraud_gov_analytics_role → Read-only on specific tables        │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ GRANT role TO user
                              │
┌─────────────────────────────────────────────────────────────────┐
│  USERS (with password, created by setup script)                 │
│  ──────────────────────────────────────────────                 │
│  fraud_gov_app_user       → LOGIN, member of app_role           │
│  fraud_gov_analytics_user → LOGIN, member of analytics_role     │
└─────────────────────────────────────────────────────────────────┘
```

### Database Tables (10 total)

| Table | Purpose |
|-------|---------|
| `rule_fields` | Defines allowed fields for rule conditions |
| `rule_field_metadata` | Extensible field metadata |
| `rules` | Logical rule identity |
| `rule_versions` | Actual rule content with JSONB condition_tree and scope |
| `rulesets` | Ruleset identity (environment, region, country, rule_type) |
| `ruleset_versions` | Ruleset version history (DRAFT → PENDING → APPROVED → ACTIVE) |
| `ruleset_version_rules` | Junction: ruleset versions contain rule versions |
| `ruleset_manifest` | Published artifact tracking (S3/MinIO) |
| `approvals` | Maker-checker workflow tracking |
| `audit_log` | Immutable audit trail |

---

**Last Updated:** 2026-01-12
