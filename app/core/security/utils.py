"""
Utility functions for user extraction and role/permission constants.

Provides helper functions for extracting user information from JWT payloads
and defines role and permission constants used throughout the application.
"""

from collections.abc import Mapping
from typing import Any

from app.core.config import settings
from app.core.errors import UnauthorizedError

ROLE_NAMES = {
    "PLATFORM_ADMIN",
    "RULE_MAKER",
    "RULE_CHECKER",
    "RULE_VIEWER",
    "FRAUD_ANALYST",
    "FRAUD_SUPERVISOR",
}


def _get_claim_value(payload: Any, claim: str, default: Any = None) -> Any:
    """Return a claim/value from a JWT payload or typed user object."""
    if isinstance(payload, Mapping):
        return payload.get(claim, default)
    return getattr(payload, claim, default)


def _resolve_audience_candidates() -> list[str]:
    """Return configured audiences in precedence order.

    Tests often patch ``settings`` with a plain mock, so this helper must
    tolerate missing properties and fall back to the underlying environment
    values.
    """

    candidates = getattr(settings, "auth0_audience_candidates", None)
    if isinstance(candidates, (list, tuple)):
        resolved = [
            str(value).strip() for value in candidates if isinstance(value, str) and value.strip()
        ]
        if resolved:
            return resolved

    resolved: list[str] = []
    for value in (
        getattr(settings, "auth0_user_audience", None),
        getattr(settings, "auth0_audience", None),
    ):
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed and trimmed not in resolved:
                resolved.append(trimmed)
    return resolved


def get_user_sub(payload: Any) -> str:
    """
    Extract the Auth0 subject (user ID) from the JWT payload.

    The 'sub' claim contains the unique user identifier from Auth0,
    typically in the format: 'google-oauth2|123456789' or 'auth0|abc123'

    Args:
        payload: Decoded JWT payload from verify_token()

    Returns:
        Auth0 subject string (user ID)

    Raises:
        UnauthorizedError: If 'sub' claim is missing
    """
    import logging

    logger = logging.getLogger(__name__)

    sub = _get_claim_value(payload, "sub")
    if not sub:
        logger.error("JWT payload missing 'sub' claim")
        raise UnauthorizedError("Invalid token - missing user identifier")
    return sub


def get_user_id(user: Any) -> str:
    """
    Extract user ID from JWT user dict.

    This is a convenience function for extracting the user ID (sub claim) from
    the user dict that's passed to route handlers after authentication.

    Args:
        user: User dict from authenticated request (contains 'sub' claim)

    Returns:
        User ID string (the 'sub' claim value)

    Example:
        @router.post("/rules")
        def create_rule(payload: RuleCreate, user: CurrentUser):
            created_by = get_user_id(user)
            ...
    """
    sub = _get_claim_value(user, "sub")
    if not sub:
        return ""
    return str(sub)


def get_user_roles(payload: Any) -> list[str]:
    """
    Extract user roles from the JWT payload.

    Roles are stored in a custom namespaced claim to avoid conflicts
    with standard JWT claims. The preferred claim key uses the unified
    user audience:
    '{AUTH0_USER_AUDIENCE}/roles'

    Note: This returns the raw roles from the token. For authorization in
    endpoints, prefer using require_permission() which works for both
    human users and M2M tokens.

    Args:
        payload: Decoded JWT payload from verify_token()

    Returns:
        List of role strings (e.g., ['PLATFORM_ADMIN', 'RULE_MAKER', 'RULE_CHECKER'])
        Returns empty list if no roles are present (common for M2M tokens)

    Example:
        roles = get_user_roles(payload)
        if 'PLATFORM_ADMIN' in roles:
            # User has admin privileges

    Role Names (must match Auth0 configuration):
        - PLATFORM_ADMIN: Platform-wide administrator
        - RULE_MAKER: Create and edit rule drafts
        - RULE_CHECKER: Review and approve rules
        - RULE_VIEWER: Read-only access
        - FRAUD_ANALYST: Analyze alerts, recommend actions
        - FRAUD_SUPERVISOR: Final decision authority
    """
    import logging

    logger = logging.getLogger(__name__)

    for audience in _resolve_audience_candidates():
        roles_claim = f"{audience}/roles"
        roles = _get_claim_value(payload, roles_claim)
        if roles is None:
            continue
        if isinstance(roles, list):
            return roles
        logger.warning(f"Roles claim is not a list: {type(roles)}")
        return []

    legacy_roles = _get_claim_value(payload, "roles", [])
    if isinstance(legacy_roles, list):
        return legacy_roles

    if legacy_roles:
        logger.warning(f"Roles claim is not a list: {type(legacy_roles)}")

    return []


def is_m2m_token(payload: Any) -> bool:
    """
    Check if the token is a Machine-to-Machine (service account) token.

    M2M tokens have:
    - 'gty' claim set to 'client-credentials'
    - No roles in the token
    - Permissions in the 'permissions' claim
    - Scope in the 'scope' claim

    Args:
        payload: Decoded JWT payload

    Returns:
        True if this is an M2M token, False otherwise
    """
    return _get_claim_value(payload, "gty") == "client-credentials"


def get_user_permissions(payload: Any) -> list[str]:
    """
    Extract permissions from the JWT payload.

    Auth0 adds permissions to human user tokens when RBAC is enabled.
    M2M tokens get permissions injected by the onExecuteCredentialsExchange
    Action (deployed by this repo's bootstrap). Both token types use the
    top-level 'permissions' array claim.

    Args:
        payload: Decoded JWT payload from verify_token()

    Returns:
        List of permission strings (e.g., ['rule:create', 'rule:read'])
        Returns empty list if no permissions are present
    """
    permissions = _get_claim_value(payload, "permissions", [])
    if isinstance(permissions, list):
        return permissions

    return []


def is_platform_admin(payload: Any) -> bool:
    """Return True when the payload/user has the PLATFORM_ADMIN role."""
    return "PLATFORM_ADMIN" in get_user_roles(payload)


def has_permission(payload: Any, required_permission: str) -> bool:
    """
    Check if the token has the required permission.

    Works for both human user tokens and M2M tokens.
    PLATFORM_ADMIN is treated as an allow-all bypass for defense in depth.

    Args:
        payload: Decoded JWT payload
        required_permission: Permission to check (e.g., 'rule:create')

    Returns:
        True if the token has the required permission, False otherwise
    """
    if is_platform_admin(payload):
        return True

    permissions = get_user_permissions(payload)
    return required_permission in permissions
