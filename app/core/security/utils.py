"""
Utility functions for user extraction and role/permission constants.

Provides helper functions for extracting user information from JWT payloads
and defines role and permission constants used throughout the application.
"""

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


def get_user_sub(payload: dict[str, Any]) -> str:
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

    sub = payload.get("sub")
    if not sub:
        logger.error("JWT payload missing 'sub' claim")
        raise UnauthorizedError("Invalid token - missing user identifier")
    return sub


def get_user_id(user: dict[str, Any]) -> str:
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
    sub = user.get("sub")
    if not sub:
        return ""
    return str(sub)


def get_user_roles(payload: dict[str, Any]) -> list[str]:
    """
    Extract user roles from the JWT payload.

    Roles are stored in a custom namespaced claim to avoid conflicts
    with standard JWT claims. The claim key uses the API audience:
    '{AUTH0_AUDIENCE}/roles' (e.g., 'https://fraud-rule-management-api/roles')

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

    roles_claim = f"{settings.auth0_audience}/roles"
    roles = payload.get(roles_claim, [])

    if not isinstance(roles, list):
        logger.warning(f"Roles claim is not a list: {type(roles)}")
        return []

    return roles


def is_m2m_token(payload: dict[str, Any]) -> bool:
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
    return payload.get("gty") == "client-credentials"


def get_user_permissions(payload: dict[str, Any]) -> list[str]:
    """
    Extract permissions from the JWT payload.

    For human user tokens, permissions are in the 'permissions' claim.
    For M2M tokens, permissions are in the 'permissions' claim or 'scope' claim.

    Args:
        payload: Decoded JWT payload from verify_token()

    Returns:
        List of permission strings (e.g., ['rule:create', 'rule:read'])
        Returns empty list if no permissions are present
    """
    permissions = payload.get("permissions", [])
    if isinstance(permissions, list) and permissions:
        return permissions

    scope = payload.get("scope", "")
    if isinstance(scope, str):
        return scope.split()

    return []


def has_permission(payload: dict[str, Any], required_permission: str) -> bool:
    """
    Check if the token has the required permission.

    Works for both human user tokens and M2M tokens.

    Args:
        payload: Decoded JWT payload
        required_permission: Permission to check (e.g., 'rule:create')

    Returns:
        True if the token has the required permission, False otherwise
    """
    permissions = get_user_permissions(payload)
    return required_permission in permissions
