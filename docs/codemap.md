# Code Map

## Repository Purpose

FastAPI control-plane service for rule authoring, approvals, and artifact publishing.

## Primary Areas

- `app/` or `src/`: service or application implementation.
- `tests/` or `e2e/`: automated validation.
- `scripts/` or `cli/`: local developer tooling.
- `docs/`: curated documentation index and section guides.

## Local Commands

- `uv sync`
- `uv run doppler-local`
- `uv run doppler-local-test`

## Test Commands

- `uv run doppler-local-test`
- `uv run doppler-test`

## API Note

Primary API surface is FastAPI under `/api/v1/*`.

## Deployment Note

Local deployment can run standalone or via platform compose apps profile.
