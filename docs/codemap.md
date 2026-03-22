# Code Map

## Repository Purpose

FastAPI control-plane service for rule authoring, approvals, and artifact publishing.
Auth0 setup is centralized in this repo, with `AUTH0_USER_AUDIENCE` shared across the portal and backend services.
This repo's Auth0 bootstrap also deploys the shared credentials-exchange Action that mirrors issued M2M access-token scopes into permissions.
Backend permission helpers treat `PLATFORM_ADMIN` as an allow-all bypass for defense in depth.
The auth boundary now returns typed `AuthenticatedUser` objects instead of raw JWT dicts.
`AuthenticatedUser` also exposes fraud analyst/supervisor helpers, and permission failures are sanitized by default.

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
- `uv run db-reset-data`
- `uv run db-reset-tables`
- `uv run db-reset-schema --yes --schema-reset-ack RESET_SHARED_SCHEMA`

HTTP metrics labels are normalized to route templates to avoid high-cardinality labels.

## Platform Modes

- Standalone mode: run this repository with its own local commands and Doppler config.
- Consolidated mode: run via `card-fraud-platform` for cross-service local validation.
