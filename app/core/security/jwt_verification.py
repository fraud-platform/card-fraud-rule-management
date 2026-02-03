"""
JWT token verification functions for Auth0 authentication.

Provides sync and async functions for verifying JWT tokens against Auth0,
extracting RSA keys from JWKS, and decoding token payloads.
"""

import logging
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.errors import UnauthorizedError

from .jwks_cache import get_jwks, get_jwks_async

logger = logging.getLogger(__name__)

# Optional security scheme for bypass mode (Authorization header is optional)
_optional_security = HTTPBearer(auto_error=False)

INVALID_OR_EXPIRED_TOKEN_MSG = "Invalid or expired token"

_ExpiredSignatureError: type[Exception] = getattr(jwt, "ExpiredSignatureError", Exception)
_JWTClaimsError: type[Exception] = getattr(jwt, "JWTClaimsError", Exception)


def _extract_rsa_key_from_jwks(jwks: dict, kid: str) -> dict[str, Any]:
    """Extract RSA key from JWKS by key ID."""
    for key in jwks.get("keys", []):
        if key["kid"] == kid:
            return {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }
    logger.error("Unable to find matching key for kid: %s", kid)
    raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)


def get_rsa_key(token: str) -> dict[str, Any]:
    """
    Extract the RSA public key from JWKS for the given token.

    Reads the token's 'kid' (key ID) header and matches it against
    the JWKS to find the corresponding public key.

    Args:
        token: JWT token string

    Returns:
        RSA public key dictionary

    Raises:
        UnauthorizedError: If key ID not found in JWKS
    """
    jwks = get_jwks()

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        logger.warning("Invalid JWT header: %s", e)
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    return _extract_rsa_key_from_jwks(jwks, unverified_header["kid"])


def verify_token(token: str) -> dict[str, Any]:
    """
    Verify JWT token against Auth0 and return the decoded payload (sync version).

    Performs comprehensive verification:
    - Signature verification using Auth0 public key
    - Issuer validation (must match AUTH0_DOMAIN)
    - Audience validation (must match AUTH0_AUDIENCE)
    - Expiration check
    - Algorithm validation (RS256)

    Args:
        token: JWT token string from Authorization header

    Returns:
        Decoded token payload containing user info and claims

    Raises:
        UnauthorizedError: If token verification fails for any reason
    """
    rsa_key = get_rsa_key(token)

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=settings.auth0_algorithms_list,
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
        logger.debug(f"Token verified successfully for subject: {payload.get('sub')}")
        return payload

    except _ExpiredSignatureError:
        logger.warning("Token has expired")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    except _JWTClaimsError as e:
        logger.warning(f"Invalid token claims: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    except Exception as e:
        logger.error(f"Unexpected error during token verification: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)


async def get_rsa_key_async(token: str) -> dict[str, Any]:
    """
    Extract the RSA public key from JWKS for the given token (async version).

    Reads the token's 'kid' (key ID) header and matches it against
    the JWKS to find the corresponding public key.

    Args:
        token: JWT token string

    Returns:
        RSA public key dictionary

    Raises:
        UnauthorizedError: If key ID not found in JWKS
    """
    jwks = await get_jwks_async()

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        logger.warning("Invalid JWT header: %s", e)
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    return _extract_rsa_key_from_jwks(jwks, unverified_header["kid"])


async def verify_token_async(token: str) -> dict[str, Any]:
    """
    Verify JWT token against Auth0 and return the decoded payload (async version).

    Performs comprehensive verification:
    - Signature verification using Auth0 public key
    - Issuer validation (must match AUTH0_DOMAIN)
    - Audience validation (must match AUTH0_AUDIENCE)
    - Expiration check
    - Algorithm validation (RS256)

    Args:
        token: JWT token string from Authorization header

    Returns:
        Decoded token payload containing user info and claims

    Raises:
        UnauthorizedError: If token verification fails for any reason
    """
    rsa_key = await get_rsa_key_async(token)

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=settings.auth0_algorithms_list,
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
        logger.debug(f"Token verified successfully for subject: {payload.get('sub')}")
        return payload

    except _ExpiredSignatureError:
        logger.warning("Token has expired")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    except _JWTClaimsError as e:
        logger.warning(f"Invalid token claims: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    except Exception as e:
        logger.error(f"Unexpected error during token verification: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)


def _create_bypass_user() -> dict[str, Any]:
    """
    Create a mock user for local development when JWT validation is bypassed.

    Returns a user with PLATFORM_ADMIN role to allow all operations for local testing.
    This is ONLY used when SECURITY_SKIP_JWT_VALIDATION=True and APP_ENV=local.
    """
    # Import os here to avoid circular import
    import os

    audience = os.environ.get("AUTH0_AUDIENCE", "https://card-fraud-governance-api")
    domain = os.environ.get("AUTH0_DOMAIN", "local.auth0.com")

    return {
        "sub": "local-dev-user",
        f"{audience}/roles": ["PLATFORM_ADMIN"],
        "permissions": [
            # Rule Management
            "rule:create",
            "rule:update",
            "rule:submit",
            "rule:approve",
            "rule:reject",
            "rule:read",
            # RuleField Management
            "rule_field:create",
            "rule_field:update",
            "rule_field:delete",
            "rule_field:read",
            # RuleSet Management
            "ruleset:create",
            "ruleset:update",
            "ruleset:submit",
            "ruleset:approve",
            "ruleset:reject",
            "ruleset:activate",
            "ruleset:compile",
            "ruleset:read",
        ],
        "aud": audience,
        "iss": f"https://{domain}/",
        "exp": 9999999999,  # Far future expiration
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_security),
) -> dict[str, Any]:
    """
    FastAPI dependency to extract and verify the current user from JWT (async version).

    This dependency:
    1. If SECURITY_SKIP_JWT_VALIDATION is enabled (APP_ENV=local only), returns a mock admin user
    2. Otherwise, extracts the Bearer token from the Authorization header
    3. Verifies the token against Auth0 (using async HTTP for JWKS)
    4. Returns the decoded user payload

    Usage:
        @router.get("/protected")
        async def protected_endpoint(user: dict = Depends(get_current_user)):
            user_id = user["sub"]
            return {"message": f"Hello {user_id}"}

    Args:
        credentials: Automatically extracted by HTTPBearer (optional when bypass enabled)

    Returns:
        Decoded JWT payload containing user information

    Raises:
        UnauthorizedError: If token is missing or invalid
    """
    # Local development bypass - ONLY allowed in LOCAL environment
    # Validation is enforced in config.py to prevent production use
    if settings.skip_jwt_validation:
        logger.info(
            "JWT validation bypassed - returning mock admin user for local development"
        )
        return _create_bypass_user()

    # Normal JWT validation flow
    if credentials is None:
        logger.warning("Missing Authorization header")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    token = credentials.credentials
    return await verify_token_async(token)
