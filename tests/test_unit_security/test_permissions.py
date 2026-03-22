"""
Tests for permission-based access control.
"""

from unittest.mock import patch

import pytest

from app.core.auth import AuthenticatedUser
from app.core.errors import ForbiddenError
from app.core.security.permissions import (
    M2M_PERMISSIONS,
    require_permission,
    require_role,
    require_roles,
)


class TestRequireRole:
    @pytest.mark.anyio
    async def test_require_role_success(self):
        with patch("app.core.security.utils.settings") as mock_settings:
            mock_settings.auth0_audience = "https://api.example.com"
            role_checker = require_role("ADMIN")

            user_payload = {"sub": "user123", "https://api.example.com/roles": ["ADMIN", "MAKER"]}

            result = role_checker(user_payload)
            assert result == user_payload

    @pytest.mark.anyio
    async def test_require_role_success_with_user_audience(self):
        with patch("app.core.security.utils.settings") as mock_settings:
            mock_settings.auth0_user_audience = "https://portal.example.com"
            mock_settings.auth0_audience = "https://service.example.com"
            role_checker = require_role("ADMIN")

            user_payload = {"sub": "user123", "https://portal.example.com/roles": ["ADMIN"]}

            result = role_checker(user_payload)
            assert result == user_payload

    @pytest.mark.anyio
    async def test_require_role_failure(self):
        role_checker = require_role("ADMIN")

        user_payload = {"sub": "user123", "https://api.example.com/roles": ["MAKER"]}

        with pytest.raises(Exception):
            role_checker(user_payload)


class TestRequirePermission:
    @pytest.mark.anyio
    async def test_require_permission_success(self):
        role_checker = require_permission("rule:create")

        user_payload = {"sub": "user123", "permissions": ["rule:create", "rule:read"]}

        result = role_checker(user_payload)
        assert result == user_payload

    @pytest.mark.anyio
    async def test_require_permission_failure(self):
        role_checker = require_permission("rule:create")

        user_payload = {"sub": "user123", "permissions": ["rule:read"]}

        with pytest.raises(Exception):
            role_checker(user_payload)

    @pytest.mark.anyio
    async def test_require_permission_platform_admin_bypass(self):
        with patch("app.core.security.utils.settings") as mock_settings:
            mock_settings.auth0_user_audience = "https://api.example.com"
            mock_settings.auth0_audience = "https://service.example.com"
            role_checker = require_permission("rule:create")

            user_payload = {"sub": "user123", "https://api.example.com/roles": ["PLATFORM_ADMIN"]}

            result = role_checker(user_payload)
            assert result == user_payload

    @pytest.mark.anyio
    async def test_require_permission_authenticated_user_bypass(self):
        role_checker = require_permission("rule:create")

        user_payload = AuthenticatedUser(
            user_id="user123", roles=["PLATFORM_ADMIN"], permissions=[]
        )

        result = role_checker(user_payload)
        assert result == user_payload

    @pytest.mark.anyio
    async def test_require_permission_sanitizes_errors_by_default(self):
        with patch("app.core.security.permissions.settings") as mock_settings:
            mock_settings.sanitize_errors = True
            role_checker = require_permission("rule:create")

            user_payload = {"sub": "user123", "permissions": ["rule:read"]}

            with pytest.raises(ForbiddenError) as exc_info:
                role_checker(user_payload)

            assert exc_info.value.details == {}

    @pytest.mark.anyio
    async def test_require_permission_includes_details_when_not_sanitized(self):
        with patch("app.core.security.permissions.settings") as mock_settings:
            mock_settings.sanitize_errors = False
            role_checker = require_permission("rule:create")

            user_payload = {"sub": "user123", "permissions": ["rule:read"]}

            with pytest.raises(ForbiddenError) as exc_info:
                role_checker(user_payload)

            assert exc_info.value.details["required_permission"] == "rule:create"
            assert exc_info.value.details["user_permissions"] == ["rule:read"]

    @pytest.mark.anyio
    async def test_require_roles_success(self):
        role_checker = require_roles("RULE_MAKER", "RULE_CHECKER")

        user_payload = {"sub": "user123", "roles": ["RULE_CHECKER"]}

        result = role_checker(user_payload)
        assert result == user_payload

    @pytest.mark.anyio
    async def test_require_roles_failure(self):
        role_checker = require_roles("RULE_MAKER", "RULE_CHECKER")

        user_payload = {"sub": "user123", "roles": ["RULE_VIEWER"]}

        with pytest.raises(ForbiddenError):
            role_checker(user_payload)

    @pytest.mark.anyio
    async def test_require_roles_failure_sanitized(self):
        with patch("app.core.security.permissions.settings") as mock_settings:
            mock_settings.sanitize_errors = True
            role_checker = require_roles("RULE_MAKER", "RULE_CHECKER")

            user_payload = {"sub": "user123", "roles": ["RULE_VIEWER"]}

            with pytest.raises(ForbiddenError) as exc_info:
                role_checker(user_payload)

            assert exc_info.value.details == {}

    @pytest.mark.anyio
    async def test_require_roles_failure_unsanitized(self):
        with patch("app.core.security.permissions.settings") as mock_settings:
            mock_settings.sanitize_errors = False
            role_checker = require_roles("RULE_MAKER", "RULE_CHECKER")

            user_payload = {"sub": "user123", "roles": ["RULE_VIEWER"]}

            with pytest.raises(ForbiddenError) as exc_info:
                role_checker(user_payload)

            assert exc_info.value.details["required_roles"] == [
                "RULE_MAKER",
                "RULE_CHECKER",
            ]


class TestM2MPermissions:
    @pytest.mark.anyio
    async def test_m2m_permissions_defined(self):
        assert "rule:create" in M2M_PERMISSIONS
        assert "rule:read" in M2M_PERMISSIONS
        assert "rule:update" in M2M_PERMISSIONS
        assert "rule:submit" in M2M_PERMISSIONS
        assert "rule:approve" in M2M_PERMISSIONS
        assert "rule:reject" in M2M_PERMISSIONS
        assert "rule_field:create" in M2M_PERMISSIONS
        assert "rule_field:read" in M2M_PERMISSIONS
        assert "ruleset:create" in M2M_PERMISSIONS
        assert "ruleset:read" in M2M_PERMISSIONS
        assert "ruleset:compile" in M2M_PERMISSIONS

    @pytest.mark.anyio
    async def test_m2m_permissions_count(self):
        assert len(M2M_PERMISSIONS) == 18
