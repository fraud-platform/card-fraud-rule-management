"""Test utilities endpoint for local development.

This endpoint provides real Auth0 tokens for testing authenticated endpoints
with Swagger UI. It is ONLY available in non-production environments.

IMPORTANT: This endpoint provides M2M tokens (client credentials flow).
For user-specific tokens (maker-checker testing), use the /test-user-token endpoint.

M2M tokens represent the client, not a specific user. When using M2M tokens
for approval workflows, maker=checker validation will REJECT the approval
because the token's sub claim is the client ID, not a user ID.

To test maker-checker workflows:
1. Use /test-user-token endpoint (requires test client with password grant)
2. Or use Auth0's Universal Login via the UI in a browser
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["test-utils"])

_TOKEN_REFRESH_SKEW_SECONDS = 60


@dataclass(frozen=True)
class _CachedAuth0Token:
    """Short-lived in-memory Auth0 token cache entry for local test helpers."""

    access_token: str
    token_type: str
    expires_at: float
    issued_at: str


def _token_cache(request: Request) -> dict[tuple[str, ...], _CachedAuth0Token]:
    """Return the cache scoped to this application process."""
    cache = getattr(request.app.state, "auth0_test_token_cache", None)
    if cache is None:
        cache = {}
        request.app.state.auth0_test_token_cache = cache
    return cache


def _get_cached_token(request: Request, key: tuple[str, ...]) -> _CachedAuth0Token | None:
    cache = _token_cache(request)
    entry = cache.get(key)
    if entry is None:
        return None
    if time.monotonic() + _TOKEN_REFRESH_SKEW_SECONDS >= entry.expires_at:
        cache.pop(key, None)
        return None
    return entry


def _cache_token(
    request: Request,
    key: tuple[str, ...],
    *,
    access_token: str,
    token_type: str,
    expires_in: int,
) -> _CachedAuth0Token:
    entry = _CachedAuth0Token(
        access_token=access_token,
        token_type=token_type,
        expires_at=time.monotonic() + expires_in,
        issued_at=datetime.now(UTC).isoformat(),
    )
    _token_cache(request)[key] = entry
    return entry


def _cached_token_response(entry: _CachedAuth0Token) -> dict[str, object]:
    """Serialize a cached token without exposing internal cache timestamps."""
    return {
        "access_token": entry.access_token,
        "token_type": entry.token_type,
        "expires_in": max(1, int(entry.expires_at - time.monotonic())),
        "issued_at": entry.issued_at,
    }


@router.get("/test-token")
async def generate_test_token(request: Request) -> dict:
    """
    Generate a real Auth0 M2M token for local development testing.

    **ONLY AVAILABLE IN NON-PRODUCTION ENVIRONMENTS**

    This endpoint calls Auth0 using Client Credentials flow to get a real JWT token
    that can be used for testing authenticated endpoints in Swagger UI or via curl.

    **IMPORTANT**: This gives an M2M token representing the CLIENT, not a USER.
    The token's `sub` claim will be the client ID (e.g.,
    "pcVcfq1F7U9WBXit3Y1QoQgc85hOQPrY@clients").
    This means maker=checker validation will REJECT approval requests.

    **For maker-checker testing**, use /test-user-token endpoint instead.

    **Requirements:**
    - AUTH0_CLIENT_ID environment variable must be set
    - AUTH0_CLIENT_SECRET environment variable must be set

    **Use in Swagger UI:**
    1. Click "Try it out"
    2. Click "Execute"
    3. Copy the "access_token" from the response
    4. Click "Authorize" button at top of page
    5. Paste the token (without "Bearer " prefix)
    6. Click "Authorize"

    **Use with curl:**
    ```bash
    # Get token
    TOKEN=$(curl -s http://127.0.0.1:8000/api/v1/test-token | jq -r '.access_token')

    # Use token in requests
    curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/rule-fields
    ```

    Returns:
        Real Auth0 JWT token valid for 1 hour

    Raises:
        403: If called in production environment
        500: If Auth0 credentials are not configured or request fails
    """
    # Block in prod
    if settings.app_env == "prod":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test token generation is not available in production",
        )

    # Check for Auth0 credentials
    client_id = settings.auth0_client_id
    client_secret = settings.auth0_client_secret

    if not client_id or not client_secret:
        logger.error("Auth0 credentials not configured for test-token endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Test endpoint not configured",
                "message": "Contact administrator to set up test token generation",
            },
        )

    # Call Auth0 to get M2M token
    token_url = f"https://{settings.auth0_domain}/oauth/token"

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": settings.auth0_audience,
        "grant_type": "client_credentials",
    }
    cache_key = ("m2m", settings.auth0_domain, client_id, settings.auth0_audience)

    try:
        cached = _get_cached_token(request, cache_key)
        if cached is not None:
            token_data = _cached_token_response(cached)
            return {
                **token_data,
                "token_category": "M2M (Client Credentials)",
                "limitations": [
                    "Token represents client, not user",
                    "maker=checker validation will REJECT approval requests",
                    "For maker-checker testing, use /test-user-token endpoint",
                ],
                "usage": {
                    "swagger_ui": "Click 'Authorize' button, paste token, click 'Authorize'",
                    "curl_example": 'curl -H "Authorization: Bearer <access-token>" http://127.0.0.1:8000/api/v1/rule-fields',
                },
            }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            auth0_data = response.json()

        access_token = auth0_data["access_token"]
        expires_in = int(auth0_data.get("expires_in", 86400))
        entry = _cache_token(
            request,
            cache_key,
            access_token=access_token,
            token_type=auth0_data.get("token_type", "Bearer"),
            expires_in=expires_in,
        )
        token_data = _cached_token_response(entry)
        logger.info("Generated M2M test token for the configured local test helper")

        return {
            **token_data,
            "token_category": "M2M (Client Credentials)",
            "limitations": [
                "Token represents client, not user",
                "maker=checker validation will REJECT approval requests",
                "For maker-checker testing, use /test-user-token endpoint",
            ],
            "usage": {
                "swagger_ui": "Click 'Authorize' button, paste token, click 'Authorize'",
                "curl_example": 'curl -H "Authorization: Bearer <access-token>" http://127.0.0.1:8000/api/v1/rule-fields',
            },
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"Auth0 token request failed: {e.response.status_code}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Authentication service unavailable",
                "message": "Failed to obtain test token from Auth0",
            },
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Failed to get token from Auth0",
                "message": str(e),
            },
        ) from e


@router.get("/test-user-token")
async def generate_test_user_token(
    request: Request,
    user: str = Query(
        default="maker",
        description="User type: 'maker', 'checker', or 'admin'",
        enum=["maker", "checker", "admin"],
    ),
) -> dict:
    """
    Generate a real Auth0 user token for maker-checker workflow testing.

    **ONLY AVAILABLE IN NON-PRODUCTION ENVIRONMENTS**

    This endpoint uses the Resource Owner Password Credentials flow to get
    tokens for specific test users. This enables testing maker-checker
    workflows where maker and checker are different users.

    **Requirements:**
    1. AUTH0_TEST_CLIENT_ID must be set with password grant enabled
    2. AUTH0_TEST_CLIENT_SECRET must be set
    3. Test users must exist in Auth0 (test-rule-maker, test-rule-checker, etc.)

    **Setup in Auth0:**
    - Create a test client with Grant Types: Password, Client Credentials
    - Configure Username-Password-Authentication connection
    - Add test users: test-rule-maker@fraud-platform.test, etc.

    **Use in Swagger UI:**
    1. Set 'user' parameter to 'maker' and execute to get maker token
    2. Click "Authorize" and paste the maker token
    3. Submit a rule for approval
    4. Set 'user' parameter to 'checker' and execute to get checker token
    5. Authorize with checker token and approve the submission

    **Use with curl:**
    ```bash
    # Get maker token
    MAKER_TOKEN=$(
        curl -s "http://127.0.0.1:8000/api/v1/test-user-token?user=maker" \
        | jq -r '.access_token'
    )

    # Get checker token
    CHECKER_TOKEN=$(
        curl -s "http://127.0.0.1:8000/api/v1/test-user-token?user=checker" \
        | jq -r '.access_token'
    )

    # Submit as maker
    curl -X POST -H "Authorization: Bearer $MAKER_TOKEN" \
        http://127.0.0.1:8000/api/v1/rule-versions/{id}/submit

    # Approve as checker
    curl -X POST -H "Authorization: Bearer $CHECKER_TOKEN" \
        http://127.0.0.1:8000/api/v1/rule-versions/{id}/approve
    ```

    Returns:
        Real Auth0 JWT token for the specified test user

    Raises:
        403: If called in production environment
        400: If invalid user parameter
        500: If Auth0 configuration is incomplete or request fails
    """
    # Block in prod
    if settings.app_env == "prod":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test token generation is not available in production",
        )

    # Map user type to test user email
    user_config: dict[str, dict[str, str]] = {
        "maker": {
            "email": "test-rule-maker@fraud-platform.test",
            "description": "Has RULE_MAKER role",
        },
        "checker": {
            "email": "test-rule-checker@fraud-platform.test",
            "description": "Has RULE_CHECKER role",
        },
        "admin": {
            "email": "test-platform-admin@fraud-platform.test",
            "description": "Has PLATFORM_ADMIN role",
        },
    }

    config = user_config.get(user)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user type: {user}. Must be 'maker', 'checker', or 'admin'",
        )

    # Check for test client credentials
    test_client_id = getattr(settings, "auth0_test_client_id", None) or os.environ.get(
        "AUTH0_TEST_CLIENT_ID", ""
    )
    test_client_secret = getattr(settings, "auth0_test_client_secret", None) or os.environ.get(
        "AUTH0_TEST_CLIENT_SECRET", ""
    )

    if not test_client_id or not test_client_secret:
        logger.error("Test client credentials not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Test user token not configured",
                "message": (
                    "Set AUTH0_TEST_CLIENT_ID and AUTH0_TEST_CLIENT_SECRET environment variables"
                ),
                "note": "The test client must have 'Password' grant type enabled in Auth0",
                "setup_steps": [
                    "1. Create or modify an Auth0 client",
                    "2. Enable 'Password' and 'Client Credentials' in Grant Types",
                    "3. Add Username-Password-Authentication connection",
                    "4. Set AUTH0_TEST_CLIENT_ID and AUTH0_TEST_CLIENT_SECRET",
                    "5. Restart the server",
                ],
            },
        )

    # Get user password from environment or settings
    password_map = {
        "maker": os.environ.get("TEST_USER_RULE_MAKER_PASSWORD", ""),
        "checker": os.environ.get("TEST_USER_RULE_CHECKER_PASSWORD", ""),
        "admin": os.environ.get("TEST_USER_PLATFORM_ADMIN_PASSWORD", ""),
    }
    user_password = password_map.get(user, "")

    if not user_password:
        logger.error(f"Password for {user} user not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "Test user password not configured",
                "message": f"Set TEST_USER_RULE_{user.upper()}_PASSWORD environment variable",
                "user": config["email"],
            },
        )

    # Call Auth0 to get user token
    token_url = f"https://{settings.auth0_domain}/oauth/token"
    payload = {
        "client_id": test_client_id,
        "client_secret": test_client_secret,
        "username": config["email"],
        "password": user_password,
        "audience": settings.auth0_user_audience_resolved,
        "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
        "realm": "Username-Password-Authentication",
        "scope": "openid profile email",
    }
    cache_key = (
        "user",
        settings.auth0_domain,
        test_client_id,
        settings.auth0_user_audience_resolved,
        config["email"],
    )

    try:
        cached = _get_cached_token(request, cache_key)
        if cached is not None:
            token_data = _cached_token_response(cached)
            return {
                **token_data,
                "token_category": "User Token (Password Grant)",
                "user_type": user,
                "user_email": config["email"],
                "roles": [config["description"]],
                "maker_checker_compatible": True,
                "usage": {
                    "swagger_ui": f"Authorize with this token, then test {user} operations",
                    "curl_example": 'curl -H "Authorization: Bearer <access-token>" http://127.0.0.1:8000/api/v1/rule-fields',
                },
            }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            auth0_data = response.json()

        access_token = auth0_data["access_token"]
        expires_in = int(auth0_data.get("expires_in", 86400))
        entry = _cache_token(
            request,
            cache_key,
            access_token=access_token,
            token_type=auth0_data.get("token_type", "Bearer"),
            expires_in=expires_in,
        )
        token_data = _cached_token_response(entry)
        logger.info("Generated user test token for role %s", user)

        return {
            **token_data,
            "token_category": "User Token (Password Grant)",
            "user_type": user,
            "user_email": config["email"],
            "roles": [config["description"]],
            "maker_checker_compatible": True,
            "usage": {
                "swagger_ui": f"Authorize with this token, then test {user} operations",
                "curl_example": 'curl -H "Authorization: Bearer <access-token>" http://127.0.0.1:8000/api/v1/rule-fields',
            },
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"Auth0 user token request failed: {e.response.status_code}")
        error_detail = {
            "error": "Failed to obtain user token from Auth0",
            "message": "Check AUTH0_TEST_CLIENT_ID/SECRET and password grant configuration",
        }
        try:
            error_body = e.response.json()
            error_detail["auth0_error"] = error_body
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to get user token from Auth0", "message": str(e)},
        ) from e
