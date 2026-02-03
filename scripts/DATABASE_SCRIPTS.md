# Database Scripts Quick Reference

## Overview

Use `setup_database.py` for all database operations. It provides multiple commands for different use cases.

| Command | Purpose | Destructive? |
|---------|---------|--------------|
| **init** | First-time setup: users + schema + seed | Partial (creates objects) |
| **reset --mode schema** | Drop & recreate schema | ✅ **YES** |
| **reset --mode data** | Truncate data only | ✅ **YES** |
| **seed** | Apply seed data | Partial |
| **verify** | Verify setup | ❌ NO |
| **create-users** | Create users only | ❌ NO |

---

## Script Details

### setup_database.py

**Unified database setup script with multiple commands.**

**Usage with Doppler (recommended):**
```powershell
# First-time setup (with passwords from Doppler)
doppler run --config local -- uv run python scripts/setup_database.py init --password-env

# Reset database (drop schema)
doppler run --config local -- uv run python scripts/setup_database.py reset --mode schema

# Reset database (truncate only)
doppler run --config local -- uv run python scripts/setup_database.py reset --mode data

# Seed data with demo content
doppler run --config local -- uv run python scripts/setup_database.py seed --demo

# Verify setup
doppler run --config local -- uv run python scripts/setup_database.py verify

# Create users only
doppler run --config local -- uv run python scripts/setup_database.py create-users --password-env
```

**Quick aliases (uv run):**
```powershell
uv run db-init           # First-time setup (local)
uv run db-init-test      # First-time setup (test)
uv run db-reset-data     # Data reset
uv run db-reset-schema   # Schema reset
uv run db-verify         # Verify setup
uv run db-seed-demo      # Seed with demo data
```

---

## Command Details

### init - First-time Setup

**Creates users, schema, indexes, and seed data.**

```powershell
doppler run --config <env> -- uv run python scripts/setup_database.py init [--demo] --password-env [--yes]
```

**Operations:**
1. Create users (fraud_gov_app_user, fraud_gov_analytics_user)
2. Create schema (fraud_gov)
3. Apply production indexes
4. Apply seed data (rule_fields)
5. Optionally apply demo data

**Flags:**
| Flag | Purpose |
|------|---------|
| `--demo` | Include demo data (rulesets, rules, approvals) |
| `--password-env` | Read passwords from Doppler (FRAUD_GOV_APP_PASSWORD, FRAUD_GOV_ANALYTICS_PASSWORD) |
| `--yes, -y` | Skip confirmation prompts |

---

### reset - Reset Database

**Two modes: schema (destructive) or data (faster).**

```powershell
# Drop and recreate everything
doppler run --config <env> -- uv run python scripts/setup_database.py reset --mode schema [--force]

# Truncate data only (preserves schema)
doppler run --config <env> -- uv run python scripts/setup_database.py reset --mode data
```

**Schema mode (destructive):**
1. DROP SCHEMA fraud_gov CASCADE
2. Recreate schema, enums, tables
3. Apply indexes
4. Reseed data

**Data mode (faster):**
1. TRUNCATE all tables (FK-safe order)
2. Reseed data

**Flags:**
| Flag | Purpose |
|------|---------|
| `--mode schema\|data` | Reset mode (default: schema) |
| `--force` | Bypass safety check for production |

---

### seed - Seed Data

**Apply seed data to existing database.**

```powershell
doppler run --config <env> -- uv run python scripts/setup_database.py seed [--demo] [--clean-first]
```

**Flags:**
| Flag | Purpose |
|------|---------|
| `--demo` | Include demo data |
| `--clean-first` | Truncate tables before seeding |

---

### verify - Verify Setup

**Check database setup status.**

```powershell
doppler run --config <env> -- uv run python scripts/setup_database.py verify
```

**Checks:**
- Users exist with correct roles
- Schema exists with all tables
- Indexes exist
- Seed data present

---

### create-users - Create Users Only

**Create database users (standalone).**

```powershell
doppler run --config <env> -- uv run python scripts/setup_database.py create-users --password-env
```

**Creates:**
- fraud_gov_app_user (full CRUD access)
- fraud_gov_analytics_user (read-only access)

---

## SQL Files Reference

| File | Purpose |
|------|---------|
| `db/fraud_governance_schema.sql` | Main schema DDL (types, tables, RLS) |
| `db/production_indexes.sql` | Performance indexes |
| `db/seed_rule_fields.sql` | Core seed data (rule fields) |
| `db/local_setup.sql` | Local Docker user setup |
| `db/create_users.sql` | Manual user creation (reference only, deprecated) |

---

## Environment Variables

Required in Doppler for each config (local, test, prod):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL_ADMIN` | Admin connection (for setup) |
| `DATABASE_URL_APP` | App user connection |
| `DATABASE_URL_ANALYTICS` | Analytics user connection |
| `FRAUD_GOV_APP_PASSWORD` | App user password |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | Analytics user password |
| `POSTGRES_ADMIN_PASSWORD` | Local Docker admin password (local only) |
| `NEON_API_KEY` | Neon API key for automation (local only) |

---

## Decision Tree

```
Need to update database?
│
├─ First-time setup (new database)?
│  └─ → init
│
├─ Need to clean everything and start over?
│  └─ → reset --mode schema
│
├─ Need to clean data but keep schema?
│  └─ → reset --mode data
│
├─ Just need to add/update seed data?
│  └─ → seed [--demo]
│
└─ Just checking if everything is set up?
   └─ → verify
```
