# Deployment Troubleshooting

## Quick Map

| Symptom | Likely Cause | First Check |
|---|---|---|
| API fails to start | Missing/invalid config | app logs + `app/core/config.py` validation rules |
| `/readyz` fails | DB connectivity/secrets issue | `DATABASE_URL_APP` and Doppler config |
| 401/403 errors | Token, audience, permission mismatch | Auth0 settings + token claims |
| Deploy works but traffic fails | Health probe mismatch or runtime vars | platform health path + env injection |

## 1) Configuration/Startup Failures

1. Check container logs first.
2. Verify required env vars are present from Doppler/platform secrets.
3. Confirm production safety constraints:
   - `APP_ENV=prod`
   - `DATABASE_URL_APP` contains `sslmode=require`
   - `AUTH0_DOMAIN` is HTTPS
   - `SECRET_KEY` length >= 32
   - `CORS_ORIGINS` has no localhost values

## 2) Database Failures

Verify DB setup with project commands:

```powershell
uv run db-verify-prod
uv run db-verify-test
```

If running locally:

```powershell
uv run local-full-setup --yes
uv run db-verify
```

## 3) Auth Failures

- Validate `AUTH0_DOMAIN` and `AUTH0_AUDIENCE` values.
- Verify permissions required by endpoint (`docs/03-api/reference.md`).
- In local/test, use `/api/v1/test-token` for fast token validation.

## 4) Test/Release Validation

```powershell
uv run doppler-test
uv run doppler-test -m smoke -v
uv run openapi
```

## 5) If Deployment Regresses

- Roll back to last known good image/version.
- Re-run smoke checks.
- Record root cause and fix in `STATUS.md`.

## Related Docs

- `production-checklist.md`
- `github-actions-cd.md`
- `../06-operations/runbooks.md`
