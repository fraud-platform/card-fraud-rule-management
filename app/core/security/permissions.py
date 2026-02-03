"""
Permission-based access control for FastAPI endpoints.

Provides FastAPI dependencies for role-based and permission-based access control.
Works for both human user tokens and M2M tokens.
"""

import logging
from typing import Any

from fastapi import Depends

from app.core.errors import ForbiddenError

from .utils import (
    get_user_permissions,
    get_user_roles,
    get_user_sub,
    has_permission,
    is_m2m_token,
)

logger = logging.getLogger(__name__)

M2M_PERMISSIONS = {
    "rule:create",
    "rule:update",
    "rule:submit",
    "rule:approve",
    "rule:reject",
    "rule:read",
    "rule_field:create",
    "rule_field:update",
    "rule_field:delete",
    "rule_field:read",
    "ruleset:create",
    "ruleset:update",
    "ruleset:submit",
    "ruleset:approve",
    "ruleset:reject",
    "ruleset:activate",
    "ruleset:compile",
    "ruleset:read",
}


def require_role(required_role: str):
    """
    Dependency factory for role-based access control.

    NOTE: This is primarily used for human users. For M2M tokens and for
    new endpoints, prefer using require_permission() directly, as it works
    for both token types and is more explicit.

    Role names (must match Auth0 configuration):
        - PLATFORM_ADMIN: Platform-wide administrator
        - RULE_MAKER: Create and edit rule drafts
        - RULE_CHECKER: Review and approve rules
        - RULE_VIEWER: Read-only access
        - FRAUD_ANALYST: Analyze alerts, recommend actions
        - FRAUD_SUPERVISOR: Final decision authority

    For M2M tokens, this function maps roles to permissions automatically.

    Args:
        required_role: The role required to access the endpoint

    Returns:
        FastAPI dependency function that checks the user's role
    """
    from app.core.dependencies import get_current_user as _deps_get_current_user

    def role_checker(user: dict[str, Any] = Depends(_deps_get_current_user)) -> dict[str, Any]:
        if is_m2m_token(user):
            permission_map = {
                "PLATFORM_ADMIN": M2M_PERMISSIONS,
                "RULE_MAKER": ["rule:create", "rule:update", "rule:submit", "rule:read"],
                "RULE_CHECKER": ["rule:approve", "rule:reject", "rule:read"],
                "RULE_VIEWER": ["rule:read", "ruleset:read"],
                "FRAUD_ANALYST": ["rule:read", "ruleset:read"],
                "FRAUD_SUPERVISOR": ["rule:read", "ruleset:read"],
            }

            required_permissions = permission_map.get(required_role, [])
            if not required_permissions:
                user_id = get_user_sub(user)
                logger.warning(
                    "Access denied - M2M token %s lacks role mapping: %s",
                    user_id,
                    required_role,
                )
                raise ForbiddenError(
                    "Insufficient permissions",
                    details={
                        "required_role": required_role,
                        "token_type": "M2M",
                        "reason": "Role not mapped to M2M permissions",
                    },
                )

            user_permissions = get_user_permissions(user)
            if not any(perm in user_permissions for perm in required_permissions):
                user_id = get_user_sub(user)
                logger.warning(
                    "Access denied - M2M token %s lacks permissions for role: %s. Token permissions: %s",
                    user_id,
                    required_role,
                    user_permissions,
                )
                raise ForbiddenError(
                    "Insufficient permissions",
                    details={
                        "required_role": required_role,
                        "required_permissions": required_permissions,
                        "token_permissions": user_permissions,
                        "token_type": "M2M",
                    },
                )

            logger.debug("M2M permission check passed for role: %s", required_role)
            return user

        roles = get_user_roles(user)

        if required_role not in roles:
            user_id = get_user_sub(user)
            logger.warning(
                "Access denied - user %s lacks required role: %s. User roles: %s",
                user_id,
                required_role,
                roles,
            )
            raise ForbiddenError(
                "Insufficient permissions",
                details={"required_role": required_role, "user_roles": roles},
            )

        logger.debug("Role check passed: user has %s role", required_role)
        return user

    return role_checker


def require_permission(required_permission: str):
    """
    Dependency factory for permission-based access control.

    Checks the 'permissions' claim in the JWT token. Works for both
    human user tokens and M2M tokens.

    Args:
        required_permission: The permission required to access the endpoint

    Returns:
        FastAPI dependency function that checks the user's permissions

    Example:
        @router.post("/rules")
        async def create_rule(user: dict = Depends(require_permission("rule:create"))):
            return {"message": "Rule created"}
    """
    from app.core.dependencies import get_current_user as _deps_get_current_user

    def permission_checker(
        user: dict[str, Any] = Depends(_deps_get_current_user),
    ) -> dict[str, Any]:
        if not has_permission(user, required_permission):
            user_id = get_user_sub(user)
            user_permissions = get_user_permissions(user)
            logger.warning(
                "Access denied - user %s lacks permission: %s. User permissions: %s",
                user_id,
                required_permission,
                user_permissions,
            )
            raise ForbiddenError(
                "Insufficient permissions",
                details={
                    "required_permission": required_permission,
                    "user_permissions": user_permissions,
                },
            )

        logger.debug("Permission check passed: user has %s", required_permission)
        return user

    return permission_checker
