# Choreo Deployment Guide

This guide provides step-by-step instructions for deploying the Fraud Rule Governance API to [Choreo](https://choreo.dev/), Ballerina's cloud-native application platform.

## Overview

**Why Choreo?**
- Free tier with 512MB RAM and 0.5 vCPU
- Built-in CI/CD from GitHub
- Automatic HTTPS and custom domains
- Integrated monitoring and logs
- Simple, developer-friendly interface
- Direct Docker container deployment

## Prerequisites

Before starting, ensure you have:
- [x] GitHub account
- [x] Choreo account (sign up at https://choreo.dev)
- [x] Dockerfile created (see [Docker Setup Guide](docker-setup.md))
- [x] Auth0 application configured
- [x] Neon PostgreSQL database created

## Step 1: Create Dockerfile

Ensure you have a production-ready Dockerfile. See [Docker Setup Guide](docker-setup.md) for the complete Dockerfile.

**Key requirements for Choreo:**
- Expose port `8080` (or configure Choreo to use port `8000`)
- Health check endpoint at `/api/v1/health`
- Non-root user for security
- Multi-stage build for smaller image size

## Step 2: Create Choreo Project

1. **Sign in to Choreo**
   - Go to https://choreo.dev
   - Click "Sign In" and authenticate with GitHub

2. **Create a New Project**
   - Click "+ Create Component"
   - Select "Docker Container" (not "REST API" or other options)
   - Click "Next"

3. **Connect GitHub Repository**
   - Select "Connect from GitHub"
   - Choose your fork or clone of the repository
   - Select the branch to deploy (usually `main` or `develop`)
   - Click "Next"

4. **Configure Build Settings**
   - **Name**: `fraud-governance-api`
   - **Dockerfile Path**: `Dockerfile` (in root)
   - **Docker Context**: `/` (root directory)
   - **Image Tag**: Leave as default (e.g., `latest`)
   - Click "Next"

5. **Configure Deployment Settings**
   - **Container Port**: `8080` (or `8000` if using default uvicorn port)
   - **Replicas**: `1` (free tier)
   - **Memory**: `512 MiB` (free tier)
   - **CPU**: `0.5` vCPU (free tier)
   - Click "Next"

6. **Health Check Configuration**
   - **Endpoint**: `/api/v1/health`
   - **Initial Delay**: `40` seconds
   - **Interval**: `30` seconds
   - **Timeout**: `10` seconds
   - **Failure Threshold**: `3`
   - Click "Next"

## Step 3: Configure Environment Variables

In Choreo, add the following environment variables in the "Deploy Configuration" section:

### Required Variables

```yaml
# Application Environment
APP_ENV: production
APP_REGION: us-east-1  # Set to your region

# Database
DATABASE_URL_APP: postgresql://user:password@host/dbname?sslmode=require

# Auth0
AUTH0_DOMAIN: your-tenant.auth0.com
AUTH0_AUDIENCE: https://fraud-governance-api

# Security
SECRET_KEY: <generate-a-32-character-random-string>

# CORS (update with your actual domain)
CORS_ORIGINS: https://your-app.choreo.dev,https://your-custom-domain.com
```

### Optional Variables

```yaml
# Observability
OBSERVABILITY_ENABLED: "true"
OBSERVABILITY_STRUCTURED_LOGS: "true"
APP_LOG_LEVEL: INFO

# Auth0 Client Credentials (only if needed for testing)
# AUTH0_CLIENT_ID: your-client-id
# AUTH0_CLIENT_SECRET: your-client-secret
```

### Adding Environment Variables in Choreo

1. Navigate to your component in Choreo console
2. Go to "Deploy Settings" -> "Configurations"
3. Click "+ Add Configuration"
4. Add each variable as a key-value pair
5. Mark sensitive variables as "Secret" (e.g., `SECRET_KEY`, database credentials)

## Step 4: Configure Secrets Management

For production, use Choreo's built-in secrets management:

### Adding Secrets

1. Go to "Deploy Settings" -> "Secrets"
2. Click "+ Add Secret"
3. Add the following secrets:
   - `DATABASE_URL_APP`: Your Neon PostgreSQL connection string
   - `SECRET_KEY`: Random 32+ character string
   - `AUTH0_CLIENT_SECRET`: If using client credentials

### Generate a Secure SECRET_KEY

```bash
# Using Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Using OpenSSL
openssl rand -base64 32

# Using PowerShell (Windows)
 powershell -Command "Add-Type -AssemblyName System.Web; [System.Web.Security.Membership]::GeneratePassword(32, 0)"
```

## Step 5: Deploy the Application

1. **Trigger Deployment**
   - Click "Deploy" in Choreo console
   - OR push to the connected branch (automatic deployment)

2. **Monitor Deployment**
   - Watch the "Build Logs" for compilation errors
   - Watch the "Deployment Logs" for runtime errors
   - Wait for health check to pass (shows "Running" status)

3. **Get the Application URL**
   - Once deployed, Choreo provides a default URL:
     - `https://your-organization.choreo.dev/fraud-governance-api`
   - Note this URL for CORS configuration

## Step 6: Verify Deployment

### Health Check

```bash
# Test health endpoint
curl https://your-app.choreo.dev/api/v1/health

# Expected response
{"ok": true}
```

### Readiness Check

```bash
# Test readiness endpoint (includes database connectivity)
curl https://your-app.choreo.dev/api/v1/readyz

# Expected response
{"ok": true, "db": "ok"}
```

### Authenticated Endpoint Test

```bash
# Get a token from Auth0
TOKEN=$(curl -s https://your-tenant.auth0.com/oauth/token \
  -H "content-type: application/json" \
  -d '{"client_id":"your-client-id","client_secret":"your-client-secret","audience":"https://fraud-governance-api","grant_type":"client_credentials"}' \
  | jq -r '.access_token')

# Test authenticated endpoint
curl -H "Authorization: Bearer $TOKEN" \
  https://your-app.choreo.dev/api/v1/rule-fields
```

## Step 7: Configure Custom Domain (Optional)

1. **Add Custom Domain**
   - Go to "Network" -> "Custom Domains"
   - Click "+ Add Domain"
   - Enter your domain (e.g., `api.yourdomain.com`)
   - Click "Verify"

2. **Configure DNS**
   - Choreo will provide a CNAME record
   - Add the CNAME record to your DNS provider:
     ```
     Type: CNAME
     Name: api
     Value: your-app.choreo.dev
     ```

3. **Update CORS**
   - Update `CORS_ORIGINS` environment variable
   - Add your custom domain to the list

## Step 8: Configure Deployment Triggers

### Automatic Deployment (Default)

- Push to `main` branch → Automatic deployment
- Choreo rebuilds Docker image on every push

### Manual Deployment

1. Go to "Deploy Settings" -> "Build Triggers"
2. Disable "Auto-deploy on push"
3. Manually click "Deploy" when ready

### Webhook Triggers

Configure webhooks for external triggers:
1. Go to "Deploy Settings" -> "Webhooks"
2. Copy the webhook URL
3. Use this URL to trigger deployments from external systems

## Step 9: View Logs and Metrics

### Access Logs

1. **Real-time Logs**
   - Go to "Observability" -> "Logs"
   - Filter by log level: INFO, WARNING, ERROR
   - Search by correlation ID: `request_id="xxx"`

2. **Log Query Examples**
   ```
   # All errors
   level:ERROR

   # Database errors
   database

   # Auth failures
   AUTH_FAILURE
   ```

### Metrics

Choreo provides built-in metrics:
- **Request Rate**: Requests per second
- **Error Rate**: Percentage of failed requests
- **Latency**: Response time percentiles (p50, p95, p99)
- **CPU/Memory**: Resource utilization

Access metrics:
1. Go to "Observability" -> "Metrics"
2. Select time range: Last 1h, 24h, 7d
3. Filter by endpoint, status code, region

## Troubleshooting

### Issue: Container fails to start

**Symptoms**: Deployment fails, "CrashLoopBackOff"

**Solutions**:
1. Check build logs for compilation errors
2. Verify environment variables are set correctly
3. Test Dockerfile locally: `docker build -t test .`
4. Check for missing dependencies in `pyproject.toml`

### Issue: Health check fails

**Symptoms**: Deployment succeeds but health check fails

**Solutions**:
1. Verify health endpoint is accessible:
   ```bash
   curl https://your-app.choreo.dev/api/v1/health
   ```
2. Check if database is accessible:
   ```bash
   # Test DATABASE_URL_APP locally
   psql "$DATABASE_URL_APP" -c "SELECT 1"
   ```
3. Increase health check initial delay (cold start)
4. Check for port mismatches (8000 vs 8080)

### Issue: Database connection fails

**Symptoms**: 500 errors, "connection refused" in logs

**Solutions**:
1. Verify `DATABASE_URL_APP` is correct
2. Check Neon database is active (not paused)
3. Ensure SSL mode is enabled: `sslmode=require`
4. Verify Neon IP allowlist includes Choreo IPs
5. Test connection locally:
   ```bash
   psql "$DATABASE_URL_APP" -c "SELECT version()"
   ```

### Issue: Auth0 authentication fails

**Symptoms**: 401 Unauthorized on all endpoints

**Solutions**:
1. Verify `AUTH0_DOMAIN` and `AUTH0_AUDIENCE` are correct
2. Check Auth0 application is enabled
3. Ensure API is configured in Auth0 with correct identifier
4. Verify token contains required roles
5. Check Auth0 logs: https://manage.auth0.com/dashboard

### Issue: CORS errors

**Symptoms**: Browser console shows CORS policy errors

**Solutions**:
1. Update `CORS_ORIGINS` to include your frontend domain
2. Ensure HTTPS URLs (not HTTP)
3. Check for typos in domain names
4. Restart deployment after updating CORS origins

### Issue: Out of memory errors

**Symptoms**: Container restarts, OOMKilled in logs

**Solutions**:
1. Check memory usage in Choreo metrics
2. Free tier is 512MB - may need to upgrade for large rulesets
3. Optimize database queries
4. Reduce connection pool size in `app/core/db.py`

## Resource Limits (Free Tier)

Choreo's free tier includes:
- **Memory**: 512 MB
- **CPU**: 0.5 vCPU
- **Storage**: 1 GB
- **Bandwidth**: 100 GB/month

**When to upgrade:**
- Compiling rulesets with > 100 rules
- High request volume (> 100 requests/second)
- Need for faster cold starts
- Production workloads

## Post-Deployment Checklist

After deployment, verify:

- [ ] Health endpoint returns 200: `curl /api/v1/health`
- [ ] Readiness endpoint returns 200: `curl /api/v1/readyz`
- [ ] Authenticated endpoints work with valid token
- [ ] Database queries succeed
- [ ] CORS is configured correctly
- [ ] Logs are streaming to Choreo
- [ ] Metrics are visible in dashboard
- [ ] Custom domain is configured (if needed)
- [ ] Auth0 application is using production tenant
- [ ] Test token endpoint is disabled (environment check)

## Monitoring and Alerting

### Set Up Alerts

1. **Error Rate Alert**
   - Go to "Observability" -> "Alerts"
   - Create alert: Error rate > 5% for 5 minutes
   - Notification: Email, Slack, or webhook

2. **Latency Alert**
   - Create alert: p95 latency > 1 second for 5 minutes
   - Helps detect performance degradation

3. **Deployment Failure Alert**
   - Enable notifications for failed deployments
   - Quick response to broken deployments

### Log Retention

Choreo retains logs for 7 days on free tier. For longer retention:
- Export logs to external SIEM (Datadog, Splunk, CloudWatch)
- Use Choreo webhooks to forward logs

## Scaling Considerations

### Vertical Scaling (Upgrade Plan)

- **Plus**: 1 GB RAM, 1 vCPU
- **Pro**: 2 GB RAM, 2 vCPU
- **Enterprise**: Custom resources

### Horizontal Scaling

Choreo supports multiple replicas:
- Increase replicas in "Deploy Settings"
- Requires paid plan
- Includes load balancer

## Next Steps

1. **Configure CI/CD**: See [GitHub Actions CD Guide](github-actions-cd.md)
2. **Security Hardening**: See [Security Hardening Guide](../06-operations/security-hardening.md)
3. **Monitoring**: See [Monitoring Guide](../06-operations/monitoring.md)
4. **Runbooks**: See [Operational Runbooks](../06-operations/runbooks.md)

---

**Related Documentation:**
- [Docker Setup](docker-setup.md)
- [GitHub Actions CD](github-actions-cd.md)
- [Production Checklist](production-checklist.md)
- [Troubleshooting](troubleshooting.md)

**Last Updated**: 2026-01-11
