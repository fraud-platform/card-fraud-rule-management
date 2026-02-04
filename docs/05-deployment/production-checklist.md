# Production Checklist

Use this checklist before deploying to production.

## 1) Secrets and Environment

- [ ] Doppler `prod` config is complete and reviewed.
- [ ] `APP_ENV=prod`.
- [ ] `DATABASE_URL_APP` uses `postgresql://...` and includes `sslmode=require`.
- [ ] `AUTH0_DOMAIN` is HTTPS.
- [ ] `CORS_ORIGINS` has no localhost values.
- [ ] `SECRET_KEY` is set and >= 32 chars.
- [ ] `METRICS_TOKEN` is set.
- [ ] Optional: `HEALTH_TOKEN` set if health endpoints should be token-protected.

## 2) Database and Storage

- [ ] Prod DB initialized (`uv run db-init-prod`).
- [ ] Prod DB verified (`uv run db-verify-prod`).
- [ ] Required indexes are present.
- [ ] Ruleset artifact backend configured (`filesystem` for local-only, `s3` for distributed/prod).
- [ ] S3/MinIO credentials and bucket verified.

## 3) Auth0 and Authorization

- [ ] Auth0 bootstrap/verification completed for target tenant.
- [ ] M2M credentials in Doppler are current.
- [ ] Permission-based endpoint access validated.
- [ ] Maker-checker SoD behavior verified in approval flows.

## 4) Quality Gates

- [ ] `uv run doppler-test` passes.
- [ ] Smoke tests pass: `uv run doppler-test -m smoke -v`.
- [ ] E2E integration tests run for release confidence (when applicable).
- [ ] `uv run lint` and `uv run format` pass.
- [ ] OpenAPI regenerated and committed when API/schema changed (`uv run openapi`).

## 5) Runtime and Observability

- [ ] `/api/v1/health` and `/api/v1/readyz` behave as expected in deployed environment.
- [ ] `/metrics` token protection verified.
- [ ] Log/metrics ingestion is active.
- [ ] Alert rules and dashboard wiring confirmed.

## 6) Deployment Readiness

- [ ] Deployment workflow references Doppler secrets correctly.
- [ ] Rollback strategy documented (image/version + DB rollback assumptions).
- [ ] Runbook links available to on-call team.

## Related Docs

- `choreo-deployment.md`
- `github-actions-cd.md`
- `troubleshooting.md`
- `../06-operations/runbooks.md`
- `../06-operations/monitoring.md`
- `../01-setup/doppler-secrets-setup.md`
