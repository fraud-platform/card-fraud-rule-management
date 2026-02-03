# New User Setup Guide

**Last Updated:** 2026-01-27
**Estimated Time:** 1-2 hours

## Overview

This guide will help you set up the **Fraud Rule Governance API** development environment from scratch. By the end, you'll have:

- A working Python development environment
- A local PostgreSQL database with the schema initialized
- Auth0 authentication configured
- A running development server
- All tests passing

## Prerequisites

### Required Tools

| Tool | Minimum Version | Required For | How to Check |
|------|----------------|--------------|--------------|
| **Python** | 3.14+ | Runtime environment | `python --version` |
| **uv** | Latest | Package manager | `uv --version` |
| **Git** | Any | Clone repository | `git --version` |
| **Docker** (optional) | Latest | Local Postgres/MinIO | `docker --version` |

### Required Accounts

| Account | Purpose | Free Tier |
|---------|---------|-----------|
| **GitHub** | Clone repository | ✅ Yes |
| **Neon** | PostgreSQL database | ✅ Yes (500h free) |
| **Doppler** | Secrets management | ✅ Yes |
| **Auth0** | Authentication | ✅ Yes (free tier) |

## Step 1: Install uv (Package Manager)

**Why uv?** Faster than pip, manages virtual environments, handles dependencies reliably.

### Windows (PowerShell)

```powershell
# Install uv using winget
winget install --id Astral-sh.uv

# Verify installation
uv --version
```

### Alternative Installation

If winget is not available:

```powershell
# Download and run the installer
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify installation
uv --version
```

## Step 2: Clone the Repository

```powershell
# Clone the repository
git clone https://github.com/your-org/card-fraud-rule-management.git
cd card-fraud-rule-management
```

## Step 3: Set Up Doppler (Secrets Management)

**Why Doppler?** Manages secrets across environments. No .env files in production.

### 3.1 Create Doppler Account

1. Go to https://doppler.com
2. Sign up for a free account
3. Download the Doppler CLI

### 3.2 Install Doppler CLI

```powershell
# Install via PowerShell (Windows)
powershell -c "irm https://cli.doppler.com/install.ps1 | iex"

# Verify installation
doppler --version
```

### 3.3 Configure Doppler Project

```powershell
# Authenticate with Doppler
doppler login

# Navigate to project directory
cd card-fraud-rule-management

# Link to existing project (or create new)
# Ask your team lead for the project name
doppler link
```

### 3.4 Verify Doppler Configuration

```powershell
# List available environments
doppler environments list

# You should see: local, test, prod
```

## Step 4: Set Up Neon PostgreSQL

**Why Neon?** Managed PostgreSQL with branching, free tier, excellent developer experience.

### 4.1 Create Neon Account

1. Go to https://neon.tech
2. Sign up for a free account
3. Create a new project

### 4.2 Create Database Branches

For development, you'll need a **test branch**:

```bash
# In Neon Console:
# 1. Go to your project
# 2. Click "Branches"
# 3. Click "Create Branch"
# 4. Name it "pytest" (for testing)
# 5. Click "Create"
```

### 4.3 Get Connection Strings

```bash
# In Neon Console:
# 1. Go to your project
# 2. Click "Connection Details"
# 3. Copy the connection string for "pytest" branch
# 4. Format: postgresql://user:pass@host/db?sslmode=require
```

### 4.4 Configure Doppler with Database URLs

Open Doppler dashboard (https://dashboard.doppler.com) and configure:

**For `test` environment:**
- `DATABASE_URL_APP`: Your Neon test branch connection string
- `DATABASE_URL_ADMIN`: Your Neon admin connection string (for schema setup)

**For `local` environment:**
- `DATABASE_URL_APP`: `postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable`
- `DATABASE_URL_ADMIN`: `postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable`

## Step 5: Set Up Auth0 (Authentication)

### 5.1 Create Auth0 Tenant

1. Go to https://auth0.com
2. Sign up for a free account
3. Create a new tenant (e.g., `fraud-gov-dev`)

### 5.2 Create an API

1. Go to **Applications** → **APIs**
2. Click **Create API**
3. Configure:
   - **Name:** Fraud Governance API
   - **Identifier:** `https://your-domain.fraud-gov-api.com` (use your domain)
   - **Signing Algorithm:** RS256
4. Click **Create**

### 5.3 Create Applications

**Create M2M Application (for API access):**

1. Go to **Applications** → **Applications**
2. Click **Create Application**
3. Choose **Machine to Machine**
4. Configure:
   - **Name:** Fraud Governance M2M
   - **API:** Fraud Governance API (select from dropdown)
5. Click **Create**

**Create Test Client (for maker-checker testing):**

1. Create another application
2. Choose **Regular Web Application**
3. Configure:
   - **Name:** Fraud Governance Test Client
   - **Allowed Callback URLs:** `http://localhost:8000/docs/callback`
   - **Allowed Logout URLs:** `http://localhost:8000`
   - **Grant Types:** Password, Client Credentials
4. Click **Create**

### 5.4 Create Roles

1. Go to **User Management** → **Roles**
2. Create each role:

**Role 1: RULE_MAKER**
```json
{
  "name": "RULE_MAKER",
  "description": "Can create and submit rules for approval",
  "permissions": ["rule:create", "rule:submit", "ruleset:update"]
}
```

**Role 2: RULE_CHECKER**
```json
{
  "name": "RULE_CHECKER",
  "description": "Can approve or reject rule changes",
  "permissions": ["rule:approve", "rule:reject", "ruleset:approve"]
}
```

**Role 3: PLATFORM_ADMIN**
```json
{
  "name": "PLATFORM_ADMIN",
  "description": "Full system access",
  "permissions": ["all"]
}
```

### 5.5 Configure Doppler with Auth0 Settings

Open Doppler dashboard and configure for `local` and `test` environments:

```
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://your-domain.fraud-gov-api.com
AUTH0_CLIENT_ID=your-m2m-client-id
AUTH0_CLIENT_SECRET=your-m2m-client-secret
AUTH0_TEST_CLIENT_ID=your-test-client-id
AUTH0_TEST_CLIENT_SECRET=your-test-client-secret
TEST_USER_RULE_MAKER_PASSWORD=maker-password
TEST_USER_RULE_CHECKER_PASSWORD=checker-password
TEST_USER_PLATFORM_ADMIN_PASSWORD=admin-password
```

## Step 6: Install Python Dependencies

```powershell
# Navigate to project root
cd card-fraud-rule-management

# Create virtual environment and install dependencies
uv sync --extra dev
```

This creates `.venv` and installs all dependencies from `pyproject.toml`.

**Expected output:** ✅ All packages installed successfully

## Step 7: Initialize Database Schema

### 7.1 Option A: Using Doppler (Recommended)

```powershell
# Initialize test database with Doppler secrets
uv run doppler-test
```

This will:
1. Connect to your Neon test database
2. Create the `fraud_gov` schema
3. Create all tables
4. Seed initial data
5. Verify the setup

### 7.2 Option B: Using Local Docker Database

```powershell
# Start PostgreSQL and MinIO
uv run infra-local-up

# Initialize local database
uv run db-init-local
```

### 7.3 Verify Database Setup

```powershell
# Run verification script
uv run db-verify-test
```

**Expected output:** ✅ All verification checks passed

## Step 8: Run Tests

```powershell
# Run all unit and smoke tests (recommended for CI/CD)
uv run doppler-test

# Run specific test types
uv run doppler-test -m smoke     # Smoke tests only
uv run doppler-test -m unit      # Unit tests only
```

**Expected output:** ✅ 224+ tests passing

## Step 9: Start Development Server

```powershell
# Start server with Doppler secrets
uv run doppler-local
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

## Step 10: Verify Setup

### 10.1 Health Check

```powershell
# Test health endpoint
curl http://localhost:8000/api/v1/health
```

**Expected response:** `{"ok": true}`

### 10.2 Readiness Check

```powershell
# Test database connectivity
curl http://localhost:8000/api/v1/readyz
```

**Expected response:** `{"ok": true, "db": "ok"}`

### 10.3 Generate Test Token

```powershell
# Get Auth0 token for testing
curl http://localhost:8000/api/v1/test-token
```

**Expected response:** JSON with `access_token` field

### 10.4 Test Authenticated Endpoint

```powershell
# Get token
$token = (curl http://localhost:8000/api/v1/test-token | ConvertFrom-Json).access_token

# Use token to access protected endpoint
curl -H "Authorization: Bearer $token" http://localhost:8000/api/v1/rule-fields
```

**Expected response:** Array of rule fields

## Step 11: Open Interactive Documentation

1. Open your browser
2. Go to http://localhost:8000/docs
3. Explore the API using Swagger UI

## Troubleshooting

### Problem: uv command not found

**Solution:**
```powershell
# Make sure uv is in your PATH
$env:Path = [System.IO.Directory]::GetFiles("C:\Users\$env:USERNAME\AppData\Local\Programs\uv", "*.exe", [System.IO.SearchOption]::AllDirectories) + $env:Path

# Or restart your terminal
```

### Problem: Database connection fails

**Solution:**
```powershell
# Verify DATABASE_URL_APP is set in Doppler
doppler secrets list

# Test connection manually
psql "$env:DATABASE_URL_APP" -c "SELECT 1"
```

### Problem: Auth0 authentication fails

**Solution:**
```powershell
# Verify Auth0 credentials in Doppler
doppler secrets list

# Check Auth0 domain is correct
# Should be: your-tenant.auth0.com (NOT https://...)
```

### Problem: Tests fail with import errors

**Solution:**
```powershell
# Make sure you're in the project root
cd card-fraud-rule-management

# Reinstall dependencies
uv sync --extra dev
```

### Problem: Port 8000 already in use

**Solution:**
```powershell
# Find process using port 8000
netstat -ano | findstr :8000

# Kill the process (replace PID)
taskkill /PID <PID> /F

# Or use a different port
uv run uvicorn app.main:app --port 8001
```

## Next Steps

Once setup is complete:

1. **Read the Architecture Documentation** [`docs/02-development/architecture.md`](../02-development/architecture.md)
2. **Explore the API** [`docs/04-api/reference.md`](../04-api/reference.md)
3. **Understand the Domain Model** [`docs/reference/domain-model.md`](../reference/domain-model.md)

## Common Commands

```powershell
# === Development ===
uv run doppler-local           # Start dev server (Doppler secrets)
uv run doppler-local-test      # Run tests against local DB

# === Testing ===
uv run doppler-test             # Tests against Neon test branch
uv run doppler-prod             # Tests against Neon prod branch
uv run doppler-test -m smoke    # Run smoke tests only

# === Database ===
uv run db-init-local            # Initialize local database
uv run db-verify-local          # Verify local database
uv run db-reset-schema-local    # Reset local database schema

# === Infrastructure ===
uv run infra-local-up           # Start PostgreSQL + MinIO
uv run infra-local-down         # Stop infrastructure

# === Code Quality ===
uv run lint                     # Check code with ruff
uv run format                   # Format code with ruff

# === Documentation ===
uv run openapi                  # Regenerate OpenAPI spec
```

## Getting Help

If you're stuck:

1. **Check the documentation:** [`docs/README.md`](../README.md)
2. **Review troubleshooting:** [`docs/03-deployment/troubleshooting.md`](../03-deployment/troubleshooting.md)
3. **Ask the team:** Create an issue or contact your team lead

## Summary

After completing this guide, you have:

✅ uv installed and configured
✅ Project cloned and dependencies installed
✅ Doppler configured for secrets management
✅ Neon PostgreSQL database set up
✅ Auth0 authentication configured
✅ Database schema initialized
✅ All tests passing
✅ Development server running
✅ API documentation accessible

**You're ready to start developing!**
