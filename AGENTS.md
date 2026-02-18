# AGENTS.md

This is the canonical instruction file for **all coding agents** working in this repository (Codex, Claude, Cursor, Copilot, etc.).

If another instruction file conflicts with this one, follow **AGENTS.md**.

---

## Cross-Repo Agent Standards

- Secrets: Doppler-only workflows. Do not create or commit `.env` files.
- Commands: use repository wrappers from `pyproject.toml` or `package.json`; avoid ad-hoc commands.
- Git hooks: run `git config core.hooksPath .githooks` after clone to enable pre-push guards.
- Docs publishing: keep only curated docs in `docs/01-setup` through `docs/07-reference`, plus `docs/README.md` and `docs/codemap.md`.
- Docs naming: use lowercase kebab-case for docs files. Exceptions: `README.md`, `codemap.md`, and generated contract files.
- Never commit docs/planning artifacts named `todo`, `status`, `archive`, or session notes.
- If behavior, routes, scripts, ports, or setup steps change, update `README.md`, `AGENTS.md`, `docs/README.md`, and `docs/codemap.md` in the same change.
- Keep health endpoint references consistent with current service contracts (for APIs, prefer `/api/v1/health`).
- Preserve shared local port conventions from `card-fraud-platform` unless an explicit migration is planned.
- Before handoff, run the repo's local lint/type/test gate and report the exact command + result.

## 1) Critical Rule: Doppler Is Mandatory

- Never use `.env` files in this project.
- Never run `uv run test` or `uv run dev` directly.
- Always use Doppler wrapper commands.

Required wrappers:
- Dev server: `uv run doppler-local`
- Tests (local DB): `uv run doppler-local-test`
- Tests (Neon test): `uv run doppler-test`
- Tests (Neon prod branch): `uv run doppler-prod`

---

## 2) Quickstart Commands

```powershell
# Install dependencies
uv sync --extra dev

# Local full setup (DB + object storage + bootstrap)
uv run local-full-setup --yes

# Run API (with Doppler local secrets)
uv run doppler-local

# Run tests (Doppler wrappers only)
uv run doppler-local-test
uv run doppler-test
uv run doppler-prod

# Lint / format
uv run lint
uv run format

# Regenerate OpenAPI
uv run openapi
```

---

## 3) Database + Infra Commands

```powershell
# Local Postgres
uv run db-local-up
uv run db-local-down
uv run db-local-reset

# Local MinIO (S3-compatible)
uv run objstore-local-up
uv run objstore-local-down
uv run objstore-local-reset
uv run objstore-local-verify

# Start/stop both DB + object store
uv run infra-local-up
uv run infra-local-down

# Schema/setup commands
uv run db-init
uv run db-init-test
uv run db-init-prod
uv run db-verify
uv run db-verify-test
uv run db-verify-prod
uv run db-reset-data
uv run db-reset-schema
uv run db-seed-demo

# Neon automation
uv run neon-setup --yes --create-compute
uv run neon-full-setup --yes
uv run db-sync-doppler-urls --yes
```

---

## 4) Auth0 Commands

```powershell
# Idempotent bootstrap / verify / cleanup
uv run auth0-bootstrap --yes --verbose
uv run auth0-verify
uv run auth0-cleanup --yes --verbose
```

Auth0 reference docs:
- `docs/07-reference/auth-model.md`
- `docs/01-setup/auth0-setup-guide.md`

---

## 5) Project Truths (Do Not Violate)

1. IDs are UUIDv7 and generated in application code.
2. Postgres schema is `fraud_gov`.
3. Driver is asyncpg (async) + psycopg v3 (sync), never psycopg2.
4. Compiler output must be deterministic (same input => same bytes).
5. Maker-checker invariant: maker cannot approve own submission.
6. Authorization is permission-based (`require_permission(...)`).

Rule type -> evaluation mode mapping:
- `ALLOWLIST` -> `FIRST_MATCH`
- `BLOCKLIST` -> `FIRST_MATCH`
- `AUTH` -> `FIRST_MATCH`
- `MONITORING` -> `ALL_MATCHING`

---

## 6) Repository Layout

- API app: `app/`
- CLI entry points: `cli/`
- DB DDL and SQL: `db/`
- Utility scripts: `scripts/`
- Tests: `tests/`
- Documentation: `docs/`

---

## 7) Documentation Policy

When code changes, update docs in the same PR.

Minimum docs to check/update:
- `README.md`
- `docs/README.md`
- `docs/03-api/reference.md` (or regenerate `docs/03-api/openapi.json` when API/schema changes)

---

## 8) Testing Policy

Use Doppler wrappers only.

Recommended flow before merge:
1. `uv run doppler-local-test`
2. `uv run doppler-test`
3. If API/schema changed: `uv run openapi`

Optional targeted runs:
- Smoke: `uv run doppler-test -m smoke -v`
- E2E integration: `uv run doppler-test -m e2e_integration -v`
- Autonomous local suite: `uv run autonomous-live-test`

---

## 9) Agent Behavior Contract

All agents should:
- Prefer repository scripts over ad-hoc commands.
- Keep changes minimal, explicit, and reversible.
- Preserve existing behavior unless change is requested.
- Avoid destructive git operations.
- Avoid introducing new tooling without clear benefit.
- Keep docs and implementation aligned.

If unsure, trust these sources in order:
1. Code in `app/`, `cli/`, `scripts/`
2. `pyproject.toml` scripts and config
3. Generated `docs/03-api/openapi.json`
4. This file (`AGENTS.md`)
5. Other docs
