# card-fraud-rule-management

FastAPI control-plane for fraud rule governance, maker-checker workflows, and deterministic RuleSet compilation.

## Critical Setup Rule

This project uses **Doppler** for secrets.

- Do not use `.env` files.
- Do not run `uv run test` / `uv run dev` directly.
- Use Doppler wrappers only.
- Auth0 setup is centralized here: `AUTH0_AUDIENCE` is the service audience, and `AUTH0_USER_AUDIENCE` is the shared user audience for the portal.

## Quick Start (PowerShell)

```powershell
# Install dependencies
uv sync --extra dev

# One-time local setup
uv run local-full-setup --yes

# Start API
uv run doppler-local

# Run tests
uv run doppler-local-test
uv run doppler-test

# Regenerate OpenAPI after API/schema changes
uv run openapi
```

## Core Capabilities

- Rule field catalog and metadata
- Rule + rule version lifecycle
- RuleSet + RuleSet version lifecycle
- Maker-checker approvals (SoD enforcement)
- Deterministic compile and publish flows
- Field registry versioning and publishing
- Audit trail and keyset pagination for list APIs

## API

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI spec: `docs/03-api/openapi.json` (generated)
- Human API guide: `docs/03-api/reference.md`
- HTTP metrics labels are normalized to route templates to avoid high-cardinality time series.

## Documentation

- Docs index: `docs/README.md`
- Agent instructions: `AGENTS.md`
- Auth model: `docs/07-reference/auth-model.md`
- Auth0 setup: `docs/01-setup/auth0-setup-guide.md`
- `uv run auth0-bootstrap --yes --verbose` also deploys the shared credentials-exchange Action that mirrors issued M2M access-token scopes into `permissions`.
- Backend permission checks grant `PLATFORM_ADMIN` a defense-in-depth bypass.
- The auth boundary now returns typed `AuthenticatedUser` objects instead of raw JWT dicts.
- `AuthenticatedUser` exposes fraud-analyst and fraud-supervisor helpers, and 403 permission errors are sanitized by default.

## Common Commands

```powershell
# Lint / format
uv run lint
uv run format

# Local infra helpers
uv run db-local-up
uv run objstore-local-up
uv run infra-local-up

# Neon setup helpers
uv run neon-full-setup --yes
uv run db-sync-doppler-urls --yes

# Controlled reset helpers
uv run db-reset-data
uv run db-reset-tables
uv run db-reset-schema --yes --schema-reset-ack RESET_SHARED_SCHEMA
```
