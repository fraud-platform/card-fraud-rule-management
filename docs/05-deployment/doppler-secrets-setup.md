# Doppler Secrets Setup (Deployment Note)

The canonical Doppler setup guide for this repository is:
- `../01-setup/doppler-secrets-setup.md`

This deployment folder file is intentionally short to avoid drift.

## Deployment-Specific Notes

- CI/CD should use Doppler service tokens (environment-scoped).
- Production deploys must use Doppler `prod` config.
- Do not export secrets into committed files.
- Do not use `.env` files.

For operational deployment details, see:
- `github-actions-cd.md`
- `choreo-deployment.md`
- `production-checklist.md`
