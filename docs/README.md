# Card Fraud Rule Management Documentation

FastAPI control-plane service for rule authoring, approvals, and artifact publishing.

## Audience

- New developers setting up this repository locally.
- Coding agents that need deterministic, executable setup/test instructions.

## Quick Start

```powershell
uv sync
uv run doppler-local
uv run doppler-local-test
```

## Documentation Standards

- Keep published docs inside `docs/01-setup` through `docs/07-reference`.
- Use lowercase kebab-case file names (for example `local-setup.md`).
- Exceptions: `README.md`, `codemap.md`, and machine-generated contract files (for example `openapi.json`).
- Do not publish TODO, session notes, or archive artifacts.

## Section Index

### `01-setup` - Setup

Prerequisites, first-run onboarding, and environment bootstrap.

- `01-setup/auth0-setup-guide.md`
- `01-setup/clean-slate-reset.md`
- `01-setup/database-setup.md`
- `01-setup/doppler-secrets-setup.md`
- `01-setup/local-setup.md`
- `01-setup/neon-api-reference.md`
- `01-setup/new-user-setup-guide.md`
- `01-setup/s3-setup.md`
- `01-setup/verification.md`

### `02-development` - Development

Day-to-day workflows, coding conventions, and contributor practices.

- `02-development/architecture.md`
- `02-development/compiler.md`
- `02-development/workflow.md`

### `03-api` - API

Contracts, schemas, endpoint examples, and integration notes.

- _No published topic file yet; see section README._

### `04-testing` - Testing

Test strategy, local commands, and validation checklists.

- _No published topic file yet; see section README._

### `05-deployment` - Deployment

Local runtime/deployment patterns and release readiness notes.

- _No published topic file yet; see section README._

### `06-operations` - Operations

Runbooks, troubleshooting, security operations, and observability.

- _No published topic file yet; see section README._

### `07-reference` - Reference

Architecture decisions, glossary, and cross-repo references.

- _No published topic file yet; see section README._

## Core Index Files

- `docs/README.md` (this index)
- `docs/codemap.md` (developer/agent orientation map)
