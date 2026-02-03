"""
Tests for permission-based access control.
"""

from unittest.mock import patch

import pytest

from app.core.security.permissions import M2M_PERMISSIONS, require_permission, require_role


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
