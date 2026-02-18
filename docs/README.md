# Card Fraud Rule Management Documentation

FastAPI control-plane service for rule authoring, approvals, and artifact publishing.

Observability note: HTTP metrics labels use normalized route templates (no raw path labels).

## Quick Start

```powershell
uv sync
uv run doppler-local
uv run doppler-local-test
```

## Documentation Standards

- Keep published docs inside `docs/01-setup` through `docs/07-reference`.
- Use lowercase kebab-case file names for topic docs.
- Exceptions: `README.md`, `codemap.md`, and generated contract artifacts (for example `openapi.json`).
- Do not keep TODO/archive/status/session planning docs in tracked documentation.

## Section Index

### `01-setup` - Setup

Prerequisites, first-run onboarding, and environment bootstrap.

- `01-setup/auth0-setup-guide.md`
- `../01-setup/clean-slate-reset.md`
- `01-setup/database-setup.md`
- `01-setup/doppler-secrets-setup.md`
- `01-setup/local-setup.md`
- `01-setup/neon-api-reference.md`
- `01-setup/new-user-setup-guide.md`
- `../01-setup/s3-setup.md`
- `01-setup/verification.md`

### `02-development` - Development

Day-to-day workflows, architecture notes, and contributor practices.

- `02-development/architecture.md`
- `02-development/compiler.md`
- `02-development/workflow.md`

### `03-api` - API

Contracts, schemas, endpoint references, and integration notes.

- `03-api/api.md`
- `03-api/openapi.json`
- `03-api/pagination.md`
- `03-api/reference.md`
- `03-api/ruleset-publisher.md`
- `03-api/ui-integration.md`

### `04-testing` - Testing

Test strategy, local commands, and validation playbooks.

- _No published topic file yet._

### `05-deployment` - Deployment

Local runtime/deployment patterns and release-readiness guidance.

- `05-deployment/choreo-deployment.md`
- `05-deployment/docker-setup.md`
- `05-deployment/doppler-secrets-setup.md`
- `05-deployment/github-actions-cd.md`
- `05-deployment/production-checklist.md`
- `05-deployment/troubleshooting.md`

### `06-operations` - Operations

Runbooks, observability, troubleshooting, and security operations.

- `06-operations/monitoring.md`
- `06-operations/runbooks.md`
- `06-operations/security-hardening.md`

### `07-reference` - Reference

ADRs, glossary, and cross-repo reference material.

- `07-reference/0001-use-doppler-for-secrets-management.md`
- `07-reference/0002-uuidv7-for-all-identifiers.md`
- `07-reference/0003-postgresql-jsonb-hybrid-storage.md`
- `07-reference/0004-maker-checker-governance.md`
- `07-reference/0005-deterministic-rule-compiler.md`
- `07-reference/0006-control-plane-runtime-separation.md`
- `07-reference/0007-velocity-state-runtime-only.md`
- `07-reference/auth-model.md`
- `07-reference/domain-model.md`
- `07-reference/external-card_fraud_rule_engine_runtime_decisions.md`
- `07-reference/external-expectations_from_rule_management.md`
- `07-reference/overview.md`

## Core Index Files

- `docs/README.md`
- `docs/codemap.md`
