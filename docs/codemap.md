# Code Map

## Repository Purpose

FastAPI control-plane service for rule authoring, approvals, and artifact publishing.

## Documentation Layout

- `01-setup/`: Setup
- `02-development/`: Development
- `03-api/`: API
- `04-testing/`: Testing
- `05-deployment/`: Deployment
- `06-operations/`: Operations
- `07-reference/`: Reference

## Local Commands

- `uv sync`
- `uv run doppler-local`
- `uv run doppler-local-test`

HTTP metrics labels are normalized to route templates to avoid high-cardinality labels.

## Platform Modes

- Standalone mode: run this repository with its own local commands and Doppler config.
- Consolidated mode: run via `card-fraud-platform` for cross-service local validation.
