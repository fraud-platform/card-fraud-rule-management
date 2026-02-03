# Setup Verification

Use this checklist after local setup to verify environment, auth, and API behavior.

## 1) Dependency and Doppler Checks

```powershell
uv --version
doppler secrets --project=card-fraud-rule-management --config=local
```

## 2) Database Checks

```powershell
uv run db-verify
```

Optional manual check:

```powershell
psql "$env:DATABASE_URL_APP" -c "SELECT current_database(), current_user;"
```

## 3) API Health Checks

Start server:

```powershell
uv run doppler-local
```

From another shell:

```powershell
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/readyz
```

Expected: both return HTTP 200.

## 4) Auth Checks (local/test only)

```powershell
$token = (Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/test-token" -Method Get).access_token
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/rules" -Method Get -Headers $headers
```

## 5) Test Suite Checks

```powershell
uv run doppler-local-test
uv run doppler-test -m smoke -v
```

Optional E2E integration:

```powershell
uv run doppler-test -m e2e_integration -v
```

## Troubleshooting

- Missing DB URL secrets: verify Doppler config and run `uv run local-full-setup --yes`.
- Auth failures: verify Auth0 values and run `uv run auth0-verify`.
- API startup errors: check Doppler secrets and required config in `app/core/config.py`.

## Related Docs

- `local-setup.md`
- `database-setup.md`
- `AUTH0_SETUP_GUIDE.md`
- `../02-development/workflow.md`
