# Local Setup

This guide sets up local development for `card-fraud-rule-management`.

## Prerequisites

- Windows PowerShell
- `uv`
- Docker Desktop (for local Postgres/MinIO)
- Doppler CLI with access to project `card-fraud-rule-management`

## 1) Install Dependencies

```powershell
uv sync --extra dev
```

## 2) Configure Doppler

```powershell
doppler login
doppler setup --project card-fraud-rule-management --config local
```

Verify access:

```powershell
doppler secrets --project=card-fraud-rule-management --config=local
```

## 3) Bootstrap Local Infra

```powershell
uv run local-full-setup --yes
```

This command initializes local services and DB setup using Doppler-managed secrets.

## 4) Start API

```powershell
uv run doppler-local
```

API endpoints:
- Swagger: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health: `http://127.0.0.1:8000/api/v1/health`

## 5) Run Tests

```powershell
uv run doppler-local-test
uv run doppler-test
```

## Important Policy

- Do not use `.env` files.
- Do not run `uv run test` or `uv run dev` directly.
- Always use Doppler wrappers.

## Related Docs

- DB setup: `database-setup.md`
- Setup verification: `verification.md`
- Auth0 setup: `AUTH0_SETUP_GUIDE.md`
- Dev workflow: `../02-development/workflow.md`
