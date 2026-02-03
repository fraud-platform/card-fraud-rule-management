# Development Workflow

This is the day-to-day workflow for contributors and coding agents.

## Non-Negotiables

- Doppler is mandatory.
- No `.env` files.
- Do not use `uv run test` / `uv run dev` directly.

## Daily Loop

```powershell
# 1) Start API
uv run doppler-local

# 2) Run tests as you work
uv run doppler-local-test

# 3) Run lint/format before commit
uv run lint
uv run format
```

## Common Task Commands

```powershell
# Focused tests
uv run doppler-test tests/test_unit_api_rules.py -v
uv run doppler-test -m smoke -v
uv run doppler-test -m e2e_integration -v

# OpenAPI refresh after API/schema changes
uv run openapi

# Local infra
uv run infra-local-up
uv run infra-local-down
```

## Code Change Checklist

1. Make the change.
2. Add or update tests.
3. Run `uv run doppler-local-test`.
4. If API changed, run `uv run openapi` and review `docs/openapi.json` diff.
5. Update docs (`README.md`, `docs/README.md`, relevant topic docs).
6. Update `STATUS.md`.

## Testing Notes

- Default pytest config excludes `e2e_integration` unless explicitly requested.
- Use Doppler wrappers so DB/Auth secrets are always present.
- Prefer targeted test runs during development and full suite before merge.

## Architecture Guardrails

- Keep repository pattern: routes -> repos/services -> DB.
- Use domain errors, not ad-hoc HTTP exceptions for business rules.
- Enforce maker-checker invariants for approval flows.
- Keep compiler output deterministic.

## Related Docs

- `architecture.md`
- `compiler.md`
- `../04-api/reference.md`
- `../01-setup/database-setup.md`
