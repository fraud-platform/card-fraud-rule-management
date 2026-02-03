# Code Map

## Core Layout

- `app/`: FastAPI application code.
  - `api/routes/`: HTTP endpoints.
  - `api/schemas/`: request/response models.
  - `compiler/`: deterministic rule compiler pipeline.
  - `repos/`: data access layer.
  - `services/`: orchestration/business services.
- `cli/`: `uv run` command entry points.
- `scripts/`: operational helpers and local setup scripts.
- `db/`: SQL/bootstrap and DB-related assets.
- `tests/`: unit, smoke, integration coverage.

## Key Commands

- `uv run doppler-local`
- `uv run doppler-local-test`
- `uv run doppler-test`
- `uv run db-init`
- `uv run infra-check`

## Integration Role

Publishes compiled ruleset artifacts and metadata used by Rule Engine runtime.
