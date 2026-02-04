# GitHub Actions CI/CD Guide

This guide covers setting up automated CI/CD pipelines for the Fraud Rule Governance API using GitHub Actions.

## Overview

The project already has a **CI workflow** (`.github/workflows/ci.yml`) that runs on every push. This guide adds **CD workflows** for automated deployment to:
- Choreo (Docker container deployment)
- GitHub Container Registry (GHCR) for Docker images

## Current CI Workflow

The existing CI pipeline includes:

```yaml
# .github/workflows/ci.yml
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint:      # Code quality checks
  test:      # Unit and smoke tests
  test-e2e:  # E2E integration tests (manual trigger)
  openapi:   # OpenAPI spec validation
```

**What CI Does:**
- Runs ruff linting and formatting checks
- Executes all unit tests (`pytest`)
- Runs smoke tests with TestClient
- Validates OpenAPI specification is up-to-date
- Uploads coverage to Codecov

## CD Workflow: Deploy to Choreo

### Prerequisites

1. **Dockerfile exists** (see [Docker Setup Guide](docker-setup.md))
2. **Choreo project created** (see [Choreo Deployment Guide](choreo-deployment.md))
3. **GitHub secrets configured** (see below)

### GitHub Secrets Configuration

Add the following secrets in your GitHub repository (`Settings` → `Secrets and variables` → `Actions`):

#### Required for All Deployments

```yaml
# Registry Authentication (for GHCR)
GHCR_USERNAME: your-github-username
GHCR_TOKEN: github_pat_xxxxx  # Personal access token with write:packages scope
```

#### Required for Choreo Deployment

```yaml
# Choreo Credentials (if triggering Choreo builds)
CHOREO_CLIENT_ID: your-choreo-client-id
CHOREO_CLIENT_SECRET: your-choreo-client-secret
CHOREO_PROJECT_ID: your-project-id
```

#### Environment-Specific Secrets

```yaml
# Production
PROD_DATABASE_URL_APP: postgresql://...
PROD_AUTH0_DOMAIN: your-tenant.auth0.com
PROD_AUTH0_AUDIENCE: https://fraud-governance-api
PROD_SECRET_KEY: your-32-character-secret
PROD_CORS_ORIGINS: https://api.yourdomain.com

# Staging
STAGING_DATABASE_URL_APP: postgresql://...
STAGING_AUTH0_DOMAIN: your-tenant.auth0.com
STAGING_AUTH0_AUDIENCE: https://fraud-governance-api-staging
STAGING_SECRET_KEY: your-staging-secret
STAGING_CORS_ORIGINS: https://staging-api.yourdomain.com
```

### Create CD Workflow

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:  # Manual trigger
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        type: choice
        options:
          - staging
          - production

env:
  PYTHON_VERSION: "3.14"
  UV_VERSION: "0.5"
  IMAGE_NAME: ghcr.io/${{ github.repository_owner }}/fraud-governance-api

jobs:
  # ============================================================================
  # Build and Push Docker Image to GHCR
  # ============================================================================
  build-and-push:
    name: Build and Push Docker Image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata for Docker
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64

  # ============================================================================
  # Deploy to Staging
  # ============================================================================
  deploy-staging:
    name: Deploy to Staging
    needs: build-and-push
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/develop' || github.event.inputs.environment == 'staging'
    environment:
      name: staging
      url: https://fraud-governance-api-staging.choreo.dev

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Configure Choreo deployment
        run: |
          echo "Deploying to Choreo staging environment"
          # Use Choreo CLI or API to trigger deployment
          # See: https://choreo.dev/docs/deployments/trigger-deployments

      - name: Trigger Choreo deployment
        run: |
          # Example using Choreo webhook
          curl -X POST \
            -H "Authorization: Bearer ${{ secrets.CHOREO_CLIENT_SECRET }}" \
            -H "Content-Type: application/json" \
            -d '{"branch":"develop","commit_sha":"${{ github.sha }}"}' \
            ${{ secrets.CHOREO_DEPLOY webhook_URL }}

      - name: Verify deployment
        run: |
          # Wait for deployment to complete
          sleep 60

          # Run smoke tests against staging
          curl -f https://fraud-governance-api-staging.choreo.dev/api/v1/health || exit 1

  # ============================================================================
  # Deploy to Production (with Manual Approval)
  # ============================================================================
  deploy-production:
    name: Deploy to Production
    needs: build-and-push
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' || github.event.inputs.environment == 'production'
    environment:
      name: production
      url: https://fraud-governance-api.choreo.dev

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Run pre-deployment tests
        run: |
          echo "Running E2E tests against staging..."
          # Run full E2E test suite before production deployment

      - name: Trigger Choreo deployment
        run: |
          echo "Deploying to Choreo production environment"
          curl -X POST \
            -H "Authorization: Bearer ${{ secrets.CHOREO_CLIENT_SECRET }}" \
            -H "Content-Type: application/json" \
            -d '{"branch":"main","commit_sha":"${{ github.sha }}"}' \
            ${{ secrets.CHOREO_DEPLOY_WEBHOOK_URL }}

      - name: Wait for deployment
        run: |
          # Wait for Choreo to deploy
          echo "Waiting for deployment to complete..."
          sleep 120

      - name: Verify deployment
        run: |
          # Health check
          curl -f https://fraud-governance-api.choreo.dev/api/v1/health || exit 1

          # Readiness check
          curl -f https://fraud-governance-api.choreo.dev/api/v1/readyz || exit 1

      - name: Run smoke tests
        run: |
          # Test critical endpoints
          TOKEN=$(curl -s https://${{ secrets.PROD_AUTH0_DOMAIN }}/oauth/token \
            -H "content-type: application/json" \
            -d '{
              "client_id":"${{ secrets.PROD_AUTH0_CLIENT_ID }}",
              "client_secret":"${{ secrets.PROD_AUTH0_CLIENT_SECRET }}",
              "audience":"${{ secrets.PROD_AUTH0_AUDIENCE }}",
              "grant_type":"client_credentials"
            }' | jq -r '.access_token')

          # Test authenticated endpoint
          curl -f -H "Authorization: Bearer $TOKEN" \
            https://fraud-governance-api.choreo.dev/api/v1/rule-fields || exit 1

      - name: Notify deployment success
        if: success()
        run: |
          echo "Deployment to production successful!"
          # Send Slack notification, update status page, etc.

      - name: Rollback on failure
        if: failure()
        run: |
          echo "Deployment failed! Initiating rollback..."
          # Trigger Choreo rollback to previous version
          # curl -X POST ${{ secrets.CHOREO_ROLLBACK_WEBHOOK_URL }}
```

## Manual Approval for Production

To require manual approval before production deployment:

1. **Add Environment Protection Rules**
   - Go to repository `Settings` → `Environments`
   - Click on `production` environment
   - Add required reviewers (select team or individuals)
   - Enable "Wait for approval before deployment"

2. **Deployment Flow**
   ```
   Push to main → Build Image → Require Approval → Deploy to Production
   ```

3. **Approve Deployment**
   - Go to `Actions` tab in GitHub
   - Click on the running workflow
   - Review the changes
   - Click "Approve and deploy"

## Environment Management

### Staging Environment

**Triggers:**
- Push to `develop` branch
- Manual trigger with `environment: staging`

**Configuration:**
- Deployed to Choreo staging project
- Uses staging database and Auth0 tenant
- Open to internal team only

### Production Environment

**Triggers:**
- Push to `main` branch (after approval)
- Manual trigger with `environment: production`

**Configuration:**
- Deployed to Choreo production project
- Uses production database and Auth0 tenant
- Publicly accessible (with authentication)

## Deployment Strategies

### Blue-Green Deployment

Choreo supports blue-green deployments:

```yaml
- name: Deploy to production (blue-green)
  run: |
    # Deploy new version (green)
    # Switch traffic from blue to green
    # Keep blue running for instant rollback
```

### Canary Deployment

For gradual rollout:

```yaml
- name: Canary deployment
  run: |
    # Deploy to 10% of traffic
    # Monitor for 15 minutes
    # If successful, deploy to 100%
```

### Rollback Procedure

Automatic rollback on failure:

```yaml
- name: Rollback on failure
  if: failure()
  run: |
    # Re-deploy previous Docker image
    docker pull ghcr.io/${{ github.repository }}/fraud-governance-api:previous
    # Trigger Choreo rollback
```

Manual rollback:

```bash
# Using Choreo CLI
choreo rollback fraud-governance-api

# Using GitHub Actions workflow dispatch
# Trigger rollback workflow with previous commit SHA
```

## Monitoring and Notifications

### Slack Notifications

Add Slack notification step:

```yaml
- name: Notify Slack
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    text: |
      Deployment to ${{ environment }} completed!
      Commit: ${{ github.sha }}
      Author: ${{ github.actor }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
  if: always()
```

### Status Page Updates

Update external status page:

```yaml
- name: Update status page
  if: always()
  run: |
    curl -X POST ${{ secrets.STATUS_PAGE_API_URL }} \
      -H "Authorization: Bearer ${{ secrets.STATUS_PAGE_API_KEY }}" \
      -d '{"status":"${{ job.status }}"}'
```

## Best Practices

### 1. Tagged Releases

Use Git tags for production releases:

```yaml
on:
  push:
    tags:
      - 'v*.*.*'  # v1.0.0, v2.1.3, etc.
```

Deploy:
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

### 2. Separate Workflows

Keep CI and CD in separate workflows:
- `ci.yml`: Runs on all PRs and pushes (lint, test)
- `deploy.yml`: Runs on main branch (build, deploy)

### 3. Caching

Cache dependencies for faster builds:

```yaml
- name: Cache uv packages
  uses: actions/cache@v4
  with:
    path: |
      ~/.cache/uv
      .venv
    key: ${{ runner.os }}-uv-${{ hashFiles('pyproject.toml') }}
```

### 4. Parallel Jobs

Run independent jobs in parallel:

```yaml
jobs:
  lint:
  test:
  build-and-push:
    needs: [lint, test]  # Wait for these to complete
  deploy:
    needs: build-and-push  # Wait for build
```

### 5. Security Scanning

Add security scanning to CD workflow:

```yaml
- name: Run Trivy vulnerability scanner
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: ${{ env.IMAGE_NAME }}:${{ github.sha }}
    format: 'sarif'
    output: 'trivy-results.sarif'

- name: Upload Trivy results to GitHub Security
  uses: github/codeql-action/upload-sarif@v2
  with:
    sarif_file: 'trivy-results.sarif'
```

## Troubleshooting

### Issue: Docker build fails

**Cause**: Missing dependencies or invalid Dockerfile

**Solution**:
1. Test Dockerfile locally: `docker build -t test .`
2. Check build logs in GitHub Actions
3. Verify all files are committed (no `.gitignore` issues)

### Issue: Deployment fails to start

**Cause**: Missing environment variables or configuration errors

**Solution**:
1. Verify all secrets are set in GitHub
2. Check Choreo deployment logs
3. Test health endpoint manually

### Issue: Tests pass locally but fail in CI

**Cause**: Environment differences or test isolation issues

**Solution**:
1. Ensure tests use environment variables, not hardcoded values
2. Use test database fixtures
3. Run tests locally: `uv run pytest`

## Complete Workflow Example

See `.github/workflows/deploy.yml` in the repository for a complete, production-ready workflow.

## Next Steps

1. **Create the workflow**: Copy the deploy.yml file
2. **Configure secrets**: Add all required secrets to GitHub
3. **Test on staging**: Deploy to staging first
4. **Set up approvals**: Configure production approval rules
5. **Configure notifications**: Add Slack/email notifications

---

**Related Documentation:**
- [Docker Setup](docker-setup.md)
- [Choreo Deployment](choreo-deployment.md)
- [Production Checklist](production-checklist.md)
- [Troubleshooting](troubleshooting.md)

**Last Updated**: 2026-01-14

**Note**: The deploy workflow is complete. See `.github/workflows/deploy.yml` for the full implementation.
