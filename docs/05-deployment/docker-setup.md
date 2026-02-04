# Docker Setup

This document describes container build and run expectations for this service.

## Key Policy

- Secrets come from Doppler/platform secret stores.
- Do not use `.env` files.

## Build

```powershell
docker build -t fraud-governance-api:latest .
```

## Runtime Requirements

At runtime, provide required environment variables through your platform (Choreo, CI/CD, Kubernetes secrets, etc.):

- `APP_ENV`
- `DATABASE_URL_APP`
- `AUTH0_DOMAIN`
- `AUTH0_AUDIENCE`
- `SECRET_KEY` (required in prod)
- `CORS_ORIGINS`
- `METRICS_TOKEN`

Optional but common:
- `DATABASE_URL_ADMIN`
- `HEALTH_TOKEN`
- S3/MinIO variables for artifact publishing

## Local Container Test (without .env files)

Use explicit `-e` flags or Doppler CLI wrapper:

```powershell
docker run --rm -p 8000:8000 `
  -e APP_ENV=local `
  -e DATABASE_URL_APP="postgresql://..." `
  -e AUTH0_DOMAIN="https://..." `
  -e AUTH0_AUDIENCE="https://..." `
  fraud-governance-api:latest
```

## Deployment Notes

- Verify health endpoint path used by platform probes: `/api/v1/health` and `/api/v1/readyz`.
- Ensure production config satisfies `app/core/config.py` validation (SSL, CORS, secret key, HTTPS Auth0 domain).
- Regenerate OpenAPI before release if API changed.

## Related Docs

- `production-checklist.md`
- `github-actions-cd.md`
- `choreo-deployment.md`
- `troubleshooting.md`
