# card-fraud-rule-management

FastAPI control-plane for fraud rule governance, maker-checker workflows, and deterministic RuleSet compilation.

## Critical Setup Rule

This project uses **Doppler** for secrets.

- Do not use `.env` files.
- Do not run `uv run test` / `uv run dev` directly.
- Use Doppler wrappers only.

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

## Documentation

- Docs index: `docs/README.md`
- Agent instructions: `AGENTS.md`
- Auth model: `docs/07-reference/auth-model.md`
- Auth0 setup: `docs/01-setup/auth0-setup-guide.md`

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
```
