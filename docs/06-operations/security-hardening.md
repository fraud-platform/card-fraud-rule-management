# Security Hardening Guide

This guide provides step-by-step instructions for addressing the P0 security issues identified in the [Production Checklist](../05-deployment/production-checklist.md).

## Overview

The following P0 security issues must be addressed before production deployment:

| Issue | Priority | Impact |
|-------|----------|--------|
| Missing security headers | P0 | Vulnerable to XSS, clickjacking |
| Sync HTTP client for JWKS | P0 | Blocking requests, poor performance |
| Health/metrics endpoints unauthenticated | P0 | Information disclosure |
| Test utilities in production | P0 | Attack surface, token generation |
| Secrets in environment variables | P0 | Credential leakage risk |

## Issue 1: Missing Security Headers

### Problem

The application does not set important security headers:
- HSTS (HTTP Strict Transport Security)
- X-Frame-Options (clickjacking protection)
- Content-Security-Policy (XSS protection)
- X-Content-Type-Options (MIME-sniffing protection)

### Impact

- Vulnerable to cross-site scripting (XSS)
- Vulnerable to clickjacking attacks
- No protection against downgrade attacks

### Solution

Create security middleware at `app/core/security_middleware.py`:

```python
"""
Security headers middleware for FastAPI.

Adds security headers to all responses:
- Strict-Transport-Security (HSTS)
- X-Frame-Options
- Content-Security-Policy (CSP)
- X-Content-Type-Options
- X-XSS-Protection
- Referrer-Policy
- Permissions-Policy
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all HTTP responses.

    Headers added:
    - Strict-Transport-Security: Enforces HTTPS connections
    - X-Frame-Options: Prevents clickjacking
    - Content-Security-Policy: Prevents XSS
    - X-Content-Type-Options: Prevents MIME-sniffing
    - X-XSS-Protection: Enables browser XSS filter
    - Referrer-Policy: Controls referrer information
    - Permissions-Policy: Controls browser features
    """

    def __init__(
        self,
        app: ASGIApp,
        hsts_max_age: int = 31536000,  # 1 year
        include_subdomains: bool = True,
        preload: bool = False,
    ) -> None:
        """
        Initialize security headers middleware.

        Args:
            app: ASGI application
            hsts_max_age: HSTS max-age in seconds (default 1 year)
            include_subdomains: Apply HSTS to all subdomains
            preload: Allow inclusion in HSTS preload list
        """
        super().__init__(app)
        self.hsts_max_age = hsts_max_age
        self.include_subdomains = include_subdomains
        self.preload = preload

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request and add security headers to response.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response with security headers added
        """
        response = await call_next(request)

        # Strict-Transport-Security (HSTS)
        # Enforces HTTPS connections for the specified time
        hsts_value = f"max-age={self.hsts_max_age}"
        if self.include_subdomains:
            hsts_value += "; includeSubDomains"
        if self.preload:
            hsts_value += "; preload"
        response.headers["Strict-Transport-Security"] = hsts_value

        # X-Frame-Options
        # Prevents clickjacking by denying framing
        response.headers["X-Frame-Options"] = "DENY"

        # Content-Security-Policy
        # Prevents XSS by restricting resource sources
        # Customize based on your actual needs
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # Needed for Swagger
            "style-src 'self' 'unsafe-inline'",  # Needed for Swagger
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # X-Content-Type-Options
        # Prevents MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-XSS-Protection
        # Enables browser's XSS filter (legacy, but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy
        # Controls how much referrer information is sent
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy (formerly Feature-Policy)
        # Controls browser features and APIs
        permissions_policy = [
            "geolocation=()",
            "microphone=()",
            "camera=()",
            "payment=()",
        ]
        response.headers["Permissions-Policy"] = ", ".join(permissions_policy)

        return response
```

### Add Middleware to Application

Update `app/main.py`:

```python
from app.core.security_middleware import SecurityHeadersMiddleware

def create_app() -> FastAPI:
    app = FastAPI(...)

    # Add security headers middleware (before CORS)
    app.add_middleware(SecurityHeadersMiddleware)

    # ... rest of middleware
```

### Configuration

For production, configure CSP headers based on your frontend:

```python
# If using a separate frontend on a different domain
csp_directives = [
    "default-src 'self'",
    f"script-src 'self' https://{FRONTEND_DOMAIN}",
    f"connect-src 'self' https://{FRONTEND_DOMAIN}",
    # ... etc
]
```

### Testing

Verify headers are set:

```bash
curl -I http://localhost:8000/api/v1/health

# Should see:
# Strict-Transport-Security: max-age=31536000; includeSubDomains
# X-Frame-Options: DENY
# Content-Security-Policy: default-src 'self'; ...
# X-Content-Type-Options: nosniff
```

## Issue 2: Synchronous HTTP Client for JWKS

### Problem

`app/core/security.py` uses `httpx.Client` (synchronous) which blocks the event loop during JWKS fetches.

### Impact

- Blocking operations reduce performance
- All requests wait during JWKS fetch
- Poor scalability under load

### Solution

Convert to async HTTP client:

```python
# In app/core/security.py

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.errors import ForbiddenError, UnauthorizedError

logger = logging.getLogger(__name__)

INVALID_OR_EXPIRED_TOKEN_MSG = "Invalid or expired token"

# CHANGED: Use AsyncClient instead of Client
# Note: We keep a sync client for compatibility with verify_token
# but will transition to fully async in a future PR
_async_http = None

async def get_async_http_client() -> httpx.AsyncClient:
    """Get or create the async HTTP client."""
    global _async_http
    if _async_http is None:
        _async_http = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _async_http


# ... rest of the code remains similar, but update JWKSCache to use async client


class JWKSCache:
    """In-memory cache for Auth0 JWKS with time-to-live (TTL) support."""

    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, Any] | None = None
        self._cache_time: datetime | None = None
        self._ttl_seconds = ttl_seconds
        self._jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        self._lock = threading.RLock()

    async def get_jwks_async(self) -> dict[str, Any]:
        """
        Get JWKS from cache or fetch from Auth0 (async version).

        Returns:
            JWKS dictionary containing signing keys

        Raises:
            UnauthorizedError: If JWKS fetch fails and no cache available
        """
        now = datetime.now(UTC)

        with self._lock:
            # Return cached JWKS if still valid
            if self._cache is not None and self._cache_time is not None:
                if now - self._cache_time < timedelta(seconds=self._ttl_seconds):
                    logger.debug("Using cached JWKS")
                    return self._cache

            # Fetch fresh JWKS
            try:
                logger.info(f"Fetching JWKS from {self._jwks_url}")
                client = await get_async_http_client()
                response = await client.get(self._jwks_url)
                response.raise_for_status()
                self._cache = response.json()
                self._cache_time = now
                logger.info("JWKS cache refreshed successfully")
                return self._cache
            except httpx.RequestError as e:
                logger.error(f"Failed to fetch JWKS: {e}")
                # Use stale cache as fallback if available
                if self._cache is not None:
                    logger.warning("Using stale JWKS cache as fallback")
                    return self._cache
                raise UnauthorizedError(
                    "Unable to verify token: authentication service unavailable"
                )

    # Keep sync version for backward compatibility
    def get_jwks(self) -> dict[str, Any]:
        """Synchronous version - will be deprecated."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.get_jwks_async())
```

**Note**: This is a significant refactor. For a quick fix, you can:

1. Keep the sync client but add a timeout
2. Increase the JWKS cache TTL to reduce fetches
3. Implement the full async refactor as a separate P1 task

## Issue 3: Health/Metrics Endpoints Unauthenticated

### Problem

Endpoints `/api/v1/health`, `/api/v1/readyz`, and `/metrics` are accessible without authentication.

### Impact

- Information disclosure (database status, metrics)
- Potential denial of service (metrics scraping)
- Violates security best practices

### Solution 1: IP-Based Authentication

For platform deployments (Choreo, AWS), use platform-level IP allowlisting:

```python
# In app/api/routes/health.py
from fastapi import Request, HTTPException

# List of allowed IPs (platform infrastructure, monitoring)
ALLOWED_METRICS_IPS = {
    "127.0.0.1",  # Localhost
    # Add Choreo/AWS monitoring IPs
}

@router.get("/metrics")
async def metrics(request: Request):
    """Prometheus metrics endpoint (IP-restricted)."""
    client_ip = request.client.host if request.client else "unknown"

    if client_ip not in ALLOWED_METRICS_IPS:
        logger.warning(f"Unauthorized metrics access from {client_ip}")
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.core.observability import metrics_endpoint
    return metrics_endpoint()
```

### Solution 2: Token-Based Authentication

For stronger security, require a bearer token:

```python
# In app/api/routes/health.py
from fastapi import Header, HTTPException
from app.core.config import settings

async def verify_metrics_token(x_metrics_token: str = Header(...)) -> None:
    """Verify metrics token."""
    expected_token = settings.metrics_token  # Add to config

    if not expected_token:
        raise HTTPException(status_code=500, detail="Metrics token not configured")

    if x_metrics_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid metrics token")

@router.get("/metrics", dependencies=[Depends(verify_metrics_token)])
async def metrics():
    """Prometheus metrics endpoint (token-protected)."""
    from app.core.observability import metrics_endpoint
    return metrics_endpoint()
```

### Configuration

Add to environment variables:

```bash
# Generate a secure token
METRICS_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Set in environment
export METRICS_TOKEN="$METRICS_TOKEN"
```

### Testing

Verify authentication works:

```bash
# Without token - should fail
curl http://localhost:8000/api/v1/metrics
# Expected: 403 Forbidden

# With token - should succeed
curl -H "X-Metrics-Token: $METRICS_TOKEN" http://localhost:8000/api/v1/metrics
# Expected: Prometheus metrics output
```

## Issue 4: Test Utilities in Production

### Problem

`/api/v1/test-token` endpoint generates real Auth0 tokens, even though it's disabled by environment check.

### Impact

- Attack surface if environment check fails
- Token generation in production is a security risk

### Solution

The endpoint is already disabled by environment check in `app/main.py`:

```python
# Test utilities (only in non-production environments)
if settings.app_env != "production":
    app.include_router(test_utils.router, prefix=API_PREFIX, tags=["test-utils"])
```

**However**, we should remove the router entirely from production builds:

### Option 1: Remove from Production (Recommended)

Update `app/main.py`:

```python
# NEVER include test utilities in production
if settings.app_env in ["local", "test"]:
    app.include_router(test_utils.router, prefix=API_PREFIX, tags=["test-utils"])
```

### Option 2: Build-Time Removal

For even stronger assurance, create a production-specific entry point:

```python
# app/main_prod.py
"""Production entry point without test utilities."""

from app.main import create_app

# Create production app (never includes test utils)
app = create_app()

# Explicitly verify no test utilities
if any(route.path.startswith("/test-token") for route in app.routes):
    raise RuntimeError("Test utilities found in production build!")
```

Update Dockerfile:

```dockerfile
# Production stage
CMD ["uvicorn", "app.main_prod:app", "--host", "0.0.0.0", "--port", "8080"]
```

## Issue 5: Secrets in Environment Variables

### Problem

Secrets are stored in environment variables and `.env` files, which can leak in logs, error messages, and core dumps.

### Impact**

- Credential exposure in logs
- Accidental commit to version control
- Accessible to anyone with container access

### Solution: Use Secret Management

For production, use a proper secret management service:

### AWS Secrets Manager

```python
# app/core/secrets.py
import json
import os

import boto3
from botocore.exceptions import ClientError


def get_secret(secret_name: str, region: str = None) -> str:
    """
    Retrieve secret from AWS Secrets Manager.

    Args:
        secret_name: Name of the secret
        region: AWS region (uses default if not specified)

    Returns:
        Secret value as string

    Raises:
        RuntimeError: If secret retrieval fails
    """
    if region:
        client = boto3.client("secretsmanager", region_name=region)
    else:
        client = boto3.client("secretsmanager")

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to retrieve secret {secret_name}: {e}")

    if "SecretString" in response:
        return response["SecretString"]
    else:
        return response["SecretBinary"]


def get_database_credentials() -> dict:
    """Get database credentials from Secrets Manager."""
    secret = get_secret("fraud-governance-api/database")
    return json.loads(secret)
```

Update `app/core/config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # In production, load secrets from secret manager
        if self.app_env == "production":
            try:
                from app.core.secrets import get_database_credentials

                # Override database URL from secrets manager
                creds = get_database_credentials()
                self.database_url_app = creds["database_url_app"]
                self.secret_key = creds["secret_key"]
            except Exception as e:
                logger.warning(f"Failed to load from secret manager: {e}")
```

### Choreo Secrets

Choreo has built-in secret management:

1. Go to "Deploy Settings" → "Secrets"
2. Add secrets as key-value pairs
3. Mark as "Secret" (encrypted at rest)
4. Access as environment variables in code

**No code changes needed** - Choreo automatically injects secrets as environment variables.

### Best Practices

1. **Never commit secrets to git**
   ```bash
   # Add to .gitignore
   .env
   .env.*
   *.pem
   *.key
   ```

2. **Rotate secrets regularly**
   - Database passwords: Every 90 days
   - API keys: Every 60 days
   - JWT secrets: Every 180 days

3. **Use different secrets per environment**
   - Development: Separate secrets
   - Staging: Separate secrets
   - Production: Separate secrets

4. **Audit secret access**
   - Enable CloudTrail for AWS Secrets Manager
   - Review access logs regularly
   - Alert on suspicious access patterns

## Security Audit Checklist

After implementing all fixes, verify:

- [ ] All security headers present (use securityheaders.com)
- [ ] JWKS fetch is non-blocking
- [ ] Health/metrics endpoints protected
- [ ] Test utilities disabled in production
- [ ] Secrets in secret manager (not .env files)
- [ ] HTTPS enforced (HSTS enabled)
- [ ] CORS configured correctly
- [ ] Rate limiting enabled
- [ ] Input validation on all endpoints
- [ ] SQL injection protection (parameterized queries)
- [ ] XSS protection (CSP headers)
- [ ] CSRF protection (if using cookies)

## Testing Security Fixes

```bash
# Test security headers
curl -I http://localhost:8000/api/v1/health

# Test metrics authentication (should fail)
curl http://localhost:8000/api/v1/metrics

# Test metrics with token (should succeed)
curl -H "X-Metrics-Token: $TOKEN" http://localhost:8000/api/v1/metrics

# Test test-token disabled in production
curl http://localhost:8000/api/v1/test-token
# Expected: 404 or 403

# Test CORS
curl -H "Origin: https://evil.com" \
  -H "Access-Control-Request-Method: POST" \
  -X OPTIONS http://localhost:8000/api/v1/rules
# Should NOT include evil.com in Access-Control-Allow-Origin
```

## Ongoing Security Maintenance

1. **Dependency updates**
   ```bash
   # Check for vulnerabilities
   uv pip list --outdated

   # Update dependencies
   uv sync --upgrade
   ```

2. **Security scanning**
   ```bash
   # Scan Docker image
   trivy image fraud-governance-api:latest

   # Scan dependencies
   safety check --json
   ```

3. **Penetration testing**
   - Quarterly security reviews
   - Third-party penetration testing
   - Bug bounty program

---

**Related Documentation:**
- [Production Checklist](../05-deployment/production-checklist.md)
- [Monitoring Guide](monitoring.md)
- [Runbooks](runbooks.md)

**Last Updated**: 2026-01-11
