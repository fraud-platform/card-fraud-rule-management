"""
Manual auth integration check (not a pytest test module).

Run with:
  doppler run --project=card-fraud-rule-management --config=local -- uv run python scripts/manual_checks/check_auth_integration.py
"""

from app.core.config import settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    clear_jwks_cache,
    get_user_permissions,
    get_user_sub,
    has_permission,
)


def test_user_extraction() -> None:
    payload = {
        "iss": settings.auth0_domain,
        "sub": "auth0|manual-check-user",
        "aud": settings.auth0_audience,
        "permissions": ["rule:read", "rule:create", "ruleset:approve"],
    }
    assert get_user_sub(payload) == "auth0|manual-check-user"
    assert "rule:read" in get_user_permissions(payload)
    assert has_permission(payload, "rule:create")
    assert not has_permission(payload, "rule:delete")


def test_missing_sub() -> None:
    payload = {"aud": settings.auth0_audience}
    try:
        get_user_sub(payload)
    except UnauthorizedError:
        return
    raise AssertionError("Expected UnauthorizedError when 'sub' is missing")


def test_cache_clear() -> None:
    clear_jwks_cache()


if __name__ == "__main__":
    test_user_extraction()
    test_missing_sub()
    test_cache_clear()
    print("[OK] auth integration manual checks passed")
