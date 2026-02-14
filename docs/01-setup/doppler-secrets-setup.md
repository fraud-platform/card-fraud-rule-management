# Doppler Secrets Setup Guide

This guide covers setting up Doppler secrets for the **card-fraud-rule-management** project.

## Overview

**Doppler** is our **primary secrets manager** for all environments:
- `local` - Local development (Docker PostgreSQL)
- `test` - CI/CD and integration testing (Neon test branch)
- `prod` - Production deployment (Neon main branch)

**Never use `.env` files** - All secrets are managed through Doppler.

## Prerequisites

1. Install Doppler CLI:
   ```powershell
   winget install doppler.cli
   ```

2. Login to Doppler:
   ```powershell
   doppler login
   ```

3. Verify access:
   ```powershell
   doppler secrets --project=card-fraud-rule-management --config=local
   ```

## This Project: Creates Database Users

**Important:** This project (`card-fraud-rule-management`) is responsible for creating the shared database users. Other projects reference these users.

## Required Secrets

### Local Config (Docker PostgreSQL)

| Secret | Value | Purpose |
|--------|-------|---------|
| `DATABASE_URL_ADMIN` | `postgresql://postgres:{POSTGRES_ADMIN_PASSWORD}@localhost:5432/fraud_gov` | Admin connection |
| `DATABASE_URL_APP` | `postgresql://fraud_gov_app_user:{FRAUD_GOV_APP_PASSWORD}@localhost:5432/fraud_gov` | App connection |
| `DATABASE_URL_ANALYTICS` | `postgresql://fraud_gov_analytics_user:{FRAUD_GOV_ANALYTICS_PASSWORD}@localhost:5432/fraud_gov` | Analytics connection |
| `FRAUD_GOV_APP_PASSWORD` | (generated) | App user password |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | (generated) | Analytics user password |
| `POSTGRES_ADMIN_PASSWORD` | `postgres` | Local admin password |
| `NEON_API_KEY` | (from Neon console) | Neon API access |
| `AUTH0_DOMAIN` | `your-tenant.auth0.com` | Auth0 authentication |
| `AUTH0_AUDIENCE` | `https://fraud-governance-api` | Auth0 API audience |
| `AUTH0_MGMT_CLIENT_ID` | (from Auth0) | Auth0 Management API |
| `AUTH0_MGMT_CLIENT_SECRET` | (from Auth0) | Auth0 Management API secret |

### Test Config (Neon Test Branch)

| Secret | Value | Purpose |
|--------|-------|---------|
| `DATABASE_URL_ADMIN` | `postgresql://fraud_gov_admin:{FRAUD_GOV_ADMIN_PASSWORD}@ep-test-xxx.neon.tech/fraud_gov?sslmode=require` | Admin connection |
| `DATABASE_URL_APP` | `postgresql://fraud_gov_app_user:{FRAUD_GOV_APP_PASSWORD}@ep-test-xxx.neon.tech/fraud_gov?sslmode=require` | App connection |
| `DATABASE_URL_ANALYTICS` | `postgresql://fraud_gov_analytics_user:{FRAUD_GOV_ANALYTICS_PASSWORD}@ep-test-xxx.neon.tech/fraud_gov?sslmode=require` | Analytics connection |
| `FRAUD_GOV_APP_PASSWORD` | (generated) | App user password |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | (generated) | Analytics user password |
| `FRAUD_GOV_ADMIN_PASSWORD` | (generated) | Admin user password |
| `AUTH0_DOMAIN` | `your-tenant.auth0.com` | Auth0 |
| `AUTH0_AUDIENCE` | `https://fraud-governance-api` | Auth0 |

### Prod Config (Neon Main Branch)

| Secret | Value | Purpose |
|--------|-------|---------|
| `DATABASE_URL_ADMIN` | `postgresql://fraud_gov_admin:{FRAUD_GOV_ADMIN_PASSWORD}@ep-prod-xxx.neon.tech/fraud_gov?sslmode=require` | Admin connection |
| `DATABASE_URL_APP` | `postgresql://fraud_gov_app_user:{FRAUD_GOV_APP_PASSWORD}@ep-prod-xxx.neon.tech/fraud_gov?sslmode=require` | App connection |
| `DATABASE_URL_ANALYTICS` | `postgresql://fraud_gov_analytics_user:{FRAUD_GOV_ANALYTICS_PASSWORD}@ep-prod-xxx.neon.tech/fraud_gov?sslmode=require` | Analytics connection |
| `FRAUD_GOV_APP_PASSWORD` | (generated) | App user password |
| `FRAUD_GOV_ANALYTICS_PASSWORD` | (generated) | Analytics user password |
| `FRAUD_GOV_ADMIN_PASSWORD` | (generated) | Admin user password |
| `AUTH0_DOMAIN` | `your-tenant.auth0.com` | Auth0 |
| `AUTH0_AUDIENCE` | `https://fraud-governance-api` | Auth0 |

## First-Time Setup

### Step 1: Generate Passwords

```powershell
# Generate strong passwords
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 2: Set Secrets in Doppler

```powershell
# Local config
doppler secrets set --project=card-fraud-rule-management --config=local FRAUD_GOV_APP_PASSWORD "<generated>"
doppler secrets set --project=card-fraud-rule-management --config=local FRAUD_GOV_ANALYTICS_PASSWORD "<generated>"
doppler secrets set --project=card-fraud-rule-management --config=local POSTGRES_ADMIN_PASSWORD "postgres"
doppler secrets set --project=card-fraud-rule-management --config=local NEON_API_KEY "<from-neon-console>"

# Test config
doppler secrets set --project=card-fraud-rule-management --config=test FRAUD_GOV_APP_PASSWORD "<generated>"
doppler secrets set --project=card-fraud-rule-management --config=test FRAUD_GOV_ANALYTICS_PASSWORD "<generated>"
doppler secrets set --project=card-fraud-rule-management --config=test FRAUD_GOV_ADMIN_PASSWORD "<generated>"

# Prod config
doppler secrets set --project=card-fraud-rule-management --config=prod FRAUD_GOV_APP_PASSWORD "<generated>"
doppler secrets set --project=card-fraud-rule-management --config=prod FRAUD_GOV_ANALYTICS_PASSWORD "<generated>"
doppler secrets set --project=card-fraud-rule-management --config=prod FRAUD_GOV_ADMIN_PASSWORD "<generated>"
```

### Step 3: Run Setup

```powershell
# Local development
uv run local-full-setup --yes

# Neon (test + prod)
uv run neon-full-setup --yes
```

## Database Users Created by This Project

This project creates shared users used by all fraud projects:

| User | Purpose | Password Secret |
|------|---------|-----------------|
| `postgres` | Local Docker superuser | `POSTGRES_ADMIN_PASSWORD` |
| `fraud_gov_admin` | DDL, migrations | `FRAUD_GOV_ADMIN_PASSWORD` |
| `fraud_gov_app` | Application CRUD | `FRAUD_GOV_APP_PASSWORD` |
| `fraud_gov_analytics` | Read-only queries | `FRAUD_GOV_ANALYTICS_PASSWORD` |

## Password Sharing with Other Projects

**Critical:** These passwords must be shared with other projects:

| Project | Secrets to Share |
|---------|-----------------|
| `card-fraud-transaction-management` | `FRAUD_GOV_APP_PASSWORD`, `FRAUD_GOV_ADMIN_PASSWORD` |
| `card-fraud-rule-engine-auth/card-fraud-rule-engine-monitoring` | `FRAUD_GOV_APP_PASSWORD` |
| `card-fraud-intelligence-portal` | `FRAUD_GOV_APP_PASSWORD`, `FRAUD_GOV_ANALYTICS_PASSWORD` |

### Sharing Passwords with card-fraud-transaction-management

```powershell
# Get passwords from this project
PASSWORD=$(doppler secrets --project=card-fraud-rule-management --config=test get FRAUD_GOV_APP_PASSWORD)

# Set in transaction-management project
doppler secrets set --project=card-fraud-transaction-management --config=test FRAUD_GOV_APP_PASSWORD "$PASSWORD"
```

## Quick Setup Commands

```powershell
# Local development
uv run local-full-setup --yes    # Start Docker + init DB
uv run doppler-local             # Run dev server
uv run doppler-local-test        # Run tests (local DB)

# Test environment
uv run db-init-test --yes        # Initialize test DB
uv run db-verify-test            # Verify setup
uv run doppler-test              # Run tests

# Prod environment
uv run db-init-prod --yes        # Initialize prod DB
uv run db-verify-prod            # Verify setup
uv run doppler-prod              # Run tests
```

## Verifying Doppler Configuration

```powershell
# Check local config
doppler secrets --project=card-fraud-rule-management --config=local

# Check test config
doppler secrets --project=card-fraud-rule-management --config=test

# Check prod config
doppler secrets --project=card-fraud-rule-management --config=prod
```

## Troubleshooting

### Issue: "DATABASE_URL not set"

```powershell
doppler configure --project=card-fraud-rule-management --config=local
```

### Issue: Password mismatch between projects

```powershell
# Compare passwords
doppler secrets --project=card-fraud-rule-management --config=test get FRAUD_GOV_APP_PASSWORD
doppler secrets --project=card-fraud-transaction-management --config=test get FRAUD_GOV_APP_PASSWORD
```

### Issue: Database users not found

Run setup to create users:
```powershell
uv run db-init --yes
```

## Related Documentation

- [Database Setup](database-setup.md) - Database initialization
- [Auth0 Setup](auth0-setup-guide.md) - Auth0 configuration
- [AGENTS.md](../../AGENTS.md) - Agent instructions

