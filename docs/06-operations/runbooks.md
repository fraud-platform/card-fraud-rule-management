# Operational Runbooks

## 1) Deployment Runbook

### Preconditions

- `uv run doppler-test` passed.
- `uv run doppler-test -m smoke -v` passed.
- OpenAPI refreshed if API/schema changed (`uv run openapi`).
- Production checklist reviewed (`../05-deployment/production-checklist.md`).

### Procedure

1. Trigger deployment pipeline.
2. Watch deploy logs.
3. Verify endpoints after deploy:
   - `/api/v1/health`
   - `/api/v1/readyz`
4. Run post-deploy smoke checks.

### Success Criteria

- Health/readiness return 200.
- No sustained increase in 5xx errors.
- Core authenticated endpoints respond correctly.

## 2) Rollback Runbook

### Trigger Conditions

- Health checks failing after deploy.
- Elevated 5xx or auth failures.
- Critical business flow regression.

### Procedure

1. Roll back to previous stable deployment artifact.
2. Re-run health/readiness checks.
3. Re-run smoke checks.
4. Capture incident details in `STATUS.md`.

## 3) Secrets Rotation Runbook

1. Rotate secret in Doppler (`test` first, then `prod`).
2. Redeploy environment.
3. Verify API startup and critical flows.
4. Record rotation timestamp and scope.

## 4) DB Incident Runbook

1. Validate connection and schema state.
2. Use `db-verify-*` commands for environment checks.
3. If recovery is needed, follow platform DB restore process.
4. Re-run smoke checks after restore.

## 5) Incident Response Checklist

- Identify severity and impact.
- Stabilize service (rollback or mitigation).
- Communicate status updates.
- Document root cause and action items.
- Update `STATUS.md` and related docs.
