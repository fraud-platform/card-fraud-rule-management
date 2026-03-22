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

from app.core.auth import AuthenticatedUser
from app.core.config import settings
from app.core.errors import UnauthorizedError

from .jwks_cache import get_jwks, get_jwks_async
from .utils import _resolve_audience_candidates, get_user_permissions, get_user_roles

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


def _decode_with_supported_audiences(token: str, rsa_key: dict[str, Any]) -> dict[str, Any]:
    """Decode a token against every configured audience until one matches."""
    last_claims_error: Exception | None = None
    audiences = _resolve_audience_candidates()
    if not audiences:
        logger.error("No Auth0 audience configured")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    for audience in audiences:
        try:
            return jwt.decode(
                token,
                rsa_key,
                algorithms=settings.auth0_algorithms_list,
                audience=audience,
                issuer=f"https://{settings.auth0_domain}/",
            )
        except _ExpiredSignatureError:
            logger.warning("Token has expired")
            raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)
        except _JWTClaimsError as e:
            last_claims_error = e
            continue
        except JWTError as e:
            logger.warning(f"JWT verification failed: {e}")
            raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    if last_claims_error is not None:
        logger.warning(f"Invalid token claims: {last_claims_error}")
    raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)


def verify_token(token: str) -> dict[str, Any]:
    """
    Verify JWT token against Auth0 and return the decoded payload (sync version).

    Performs comprehensive verification:
    - Signature verification using Auth0 public key
    - Issuer validation (must match AUTH0_DOMAIN)
    - Audience validation (must match the configured user or service audience)
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
        payload = _decode_with_supported_audiences(token, rsa_key)
        logger.debug(f"Token verified successfully for subject: {payload.get('sub')}")
        return payload
    except UnauthorizedError:
        raise
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
    - Audience validation (must match the configured user or service audience)
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
        payload = _decode_with_supported_audiences(token, rsa_key)
        logger.debug(f"Token verified successfully for subject: {payload.get('sub')}")
        return payload
    except UnauthorizedError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during token verification: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)


def _create_bypass_user() -> AuthenticatedUser:
    """
    Create a mock user for local development when JWT validation is bypassed.

    Returns a user with PLATFORM_ADMIN role to allow all operations for local testing.
    This is ONLY used when SECURITY_SKIP_JWT_VALIDATION=True and APP_ENV=local.
    """
    # Keep the bypass user aligned with the transaction-management model:
    # a typed authenticated user with PLATFORM_ADMIN access and full rule permissions.
    return AuthenticatedUser(
        user_id="local-dev-user",
        email="local-dev@example.com",
        name="Local Development User",
        roles=["PLATFORM_ADMIN"],
        permissions=[
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
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_security),
) -> AuthenticatedUser:
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
            user_id = user.user_id
            return {"message": f"Hello {user_id}"}

    Args:
        credentials: Automatically extracted by HTTPBearer (optional when bypass enabled)

    Returns:
        AuthenticatedUser containing user information

    Raises:
        UnauthorizedError: If token is missing or invalid
    """
    # Local development bypass - ONLY allowed in LOCAL environment
    # Validation is enforced in config.py to prevent production use
    if settings.skip_jwt_validation:
        logger.info("JWT validation bypassed - returning mock admin user for local development")
        return _create_bypass_user()

    # Normal JWT validation flow
    if credentials is None:
        logger.warning("Missing Authorization header")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    token = credentials.credentials
    payload = await verify_token_async(token)
    return AuthenticatedUser(
        user_id=payload.get("sub", ""),
        email=payload.get("email"),
        name=payload.get("name"),
        roles=get_user_roles(payload),
        permissions=get_user_permissions(payload),
    )
