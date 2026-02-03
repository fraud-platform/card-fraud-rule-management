"""
Security module - Auth0 JWT token verification and authentication utilities.

This module has been refactored into focused submodules:

- circuit_breaker.py: Circuit breaker pattern for external service failures
- jwks_cache.py: JWKS cache with TTL support
- jwt_verification.py: JWT verification functions
- permissions.py: Permission-based access control dependencies
- utils.py: Utility functions and constants

Import directly from this module, or from submodules for more granular access.
"""

import logging

from jose import JWTError, jwt

from app.core.config import settings

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
)
from .jwks_cache import (
    JWKSCache,
    _jwks_cache,
    clear_jwks_cache,
    close_async_http_client,
    get_async_http_client,
    get_jwks,
    get_jwks_async,
)
from .jwt_verification import (
    INVALID_OR_EXPIRED_TOKEN_MSG,
    _optional_security,
    get_current_user,
    get_rsa_key,
    get_rsa_key_async,
    verify_token,
    verify_token_async,
)

# Alias for backward compatibility
security = _optional_security
from .permissions import (
    M2M_PERMISSIONS,
    require_permission,
    require_role,
)
from .utils import (
    ROLE_NAMES,
    get_user_id,
    get_user_permissions,
    get_user_roles,
    get_user_sub,
    has_permission,
    is_m2m_token,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitBreakerState",
    "INVALID_OR_EXPIRED_TOKEN_MSG",
    "JWTError",
    "logger",
    "M2M_PERMISSIONS",
    "ROLE_NAMES",
    "settings",
    "_jwks_cache",
    "clear_jwks_cache",
    "close_async_http_client",
    "get_async_http_client",
    "get_current_user",
    "get_jwks",
    "get_jwks_async",
    "get_rsa_key",
    "get_rsa_key_async",
    "get_user_id",
    "get_user_permissions",
    "get_user_roles",
    "get_user_sub",
    "has_permission",
    "is_m2m_token",
    "JWKSCache",
    "jwt",
    "require_permission",
    "require_role",
    "security",
    "verify_token",
    "verify_token_async",
]
