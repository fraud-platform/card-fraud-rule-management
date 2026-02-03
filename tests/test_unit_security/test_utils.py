"""
Tests for utility functions in security module.
"""

from unittest.mock import patch

import pytest

from app.core.security.utils import (
    ROLE_NAMES,
    get_user_id,
    get_user_permissions,
    get_user_roles,
    get_user_sub,
    has_permission,
    is_m2m_token,
)


class TestGetUserSub:
    @pytest.mark.anyio
    async def test_get_user_sub(self):
        payload = {"sub": "user123"}
        assert get_user_sub(payload) == "user123"

    @pytest.mark.anyio
    async def test_get_user_sub_missing(self):
        payload = {}
        with pytest.raises(Exception):
            get_user_sub(payload)

    @pytest.mark.anyio
    async def test_get_user_sub_with_empty_string(self):
        payload = {"sub": ""}
        with pytest.raises(Exception):
            get_user_sub(payload)

    @pytest.mark.anyio
    async def test_get_user_sub_with_none(self):
        payload = {"sub": None}
        with pytest.raises(Exception):
            get_user_sub(payload)


class TestGetUserRoles:
    @pytest.mark.anyio
    async def test_get_user_roles(self):
        payload = {"https://api.example.com/roles": ["ADMIN", "MAKER"]}
        with patch("app.core.security.utils.settings") as mock_settings:
            mock_settings.auth0_audience = "https://api.example.com"
            roles = get_user_roles(payload)
            assert roles == ["ADMIN", "MAKER"]

    @pytest.mark.anyio
    async def test_get_user_roles_missing(self):
        payload = {}
        roles = get_user_roles(payload)
        assert roles == []

    @pytest.mark.anyio
    async def test_get_user_roles_malformed(self):
        payload = {"https://api.example.com/roles": "not-a-list"}
        roles = get_user_roles(payload)
        assert roles == []

    @pytest.mark.anyio
    async def test_get_user_roles_with_list(self):
        payload = {"https://api.example.com/roles": ["ADMIN"]}
        with patch("app.core.security.utils.settings") as mock_settings:
            mock_settings.auth0_audience = "https://api.example.com"
            roles = get_user_roles(payload)
            assert roles == ["ADMIN"]


class TestGetUserPermissions:
    @pytest.mark.anyio
    async def test_get_user_permissions_from_list(self):
        payload = {"permissions": ["rule:create", "rule:read"]}
        permissions = get_user_permissions(payload)
        assert permissions == ["rule:create", "rule:read"]

    @pytest.mark.anyio
    async def test_get_user_permissions_from_scope(self):
        payload = {"scope": "rule:create rule:read rule:update"}
        permissions = get_user_permissions(payload)
        assert permissions == ["rule:create", "rule:read", "rule:update"]

    @pytest.mark.anyio
    async def test_get_user_permissions_empty(self):
        payload = {}
        permissions = get_user_permissions(payload)
        assert permissions == []

    @pytest.mark.anyio
    async def test_get_user_permissions_prefers_list(self):
        payload = {"permissions": ["rule:create"], "scope": "rule:read"}
        permissions = get_user_permissions(payload)
        assert permissions == ["rule:create"]


class TestHasPermission:
    @pytest.mark.anyio
    async def test_has_permission_true(self):
        payload = {"permissions": ["rule:create", "rule:read"]}
        assert has_permission(payload, "rule:create") is True

    @pytest.mark.anyio
    async def test_has_permission_false(self):
        payload = {"permissions": ["rule:read"]}
        assert has_permission(payload, "rule:create") is False

    @pytest.mark.anyio
    async def test_has_permission_empty(self):
        payload = {}
        assert has_permission(payload, "rule:create") is False


class TestIsM2MToken:
    @pytest.mark.anyio
    async def test_is_m2m_token_true(self):
        payload = {"gty": "client-credentials"}
        assert is_m2m_token(payload) is True

    @pytest.mark.anyio
    async def test_is_m2m_token_false(self):
        payload = {"sub": "user123"}
        assert is_m2m_token(payload) is False

    @pytest.mark.anyio
    async def test_is_m2m_token_missing_gty(self):
        payload = {}
        assert is_m2m_token(payload) is False


class TestGetUserId:
    @pytest.mark.anyio
    async def test_get_user_id_with_sub(self):
        user = {"sub": "auth0|123456"}
        assert get_user_id(user) == "auth0|123456"

    @pytest.mark.anyio
    async def test_get_user_id_with_string_sub(self):
        user = {"sub": "google-oauth2|789012"}
        assert get_user_id(user) == "google-oauth2|789012"

    @pytest.mark.anyio
    async def test_get_user_id_missing_sub(self):
        user = {}
        assert get_user_id(user) == ""

    @pytest.mark.anyio
    async def test_get_user_id_none_sub(self):
        user = {"sub": None}
        assert get_user_id(user) == ""


class TestRoleNames:
    @pytest.mark.anyio
    async def test_role_names_contains_expected_roles(self):
        assert "PLATFORM_ADMIN" in ROLE_NAMES
        assert "RULE_MAKER" in ROLE_NAMES
        assert "RULE_CHECKER" in ROLE_NAMES
        assert "RULE_VIEWER" in ROLE_NAMES
        assert "FRAUD_ANALYST" in ROLE_NAMES
        assert "FRAUD_SUPERVISOR" in ROLE_NAMES

    @pytest.mark.anyio
    async def test_role_names_count(self):
        assert len(ROLE_NAMES) == 6
