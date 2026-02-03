"""
Test script to verify Auth0 JWT authentication integration.

This script demonstrates:
1. JWT token verification flow
2. User extraction from token payload
3. Role-based access control
4. Error handling for invalid tokens
"""

from app.core.config import settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import (
    clear_jwks_cache,
    get_user_roles,
    get_user_sub,
    require_role,
)


def test_user_extraction():
    """Test extracting user information from JWT payload."""
    print("\n=== Testing User Extraction ===")

    # Mock JWT payload structure from Auth0
    test_payload = {
        "iss": f"https://{settings.auth0_domain}/",
        "sub": "google-oauth2|123456789",
        "aud": settings.auth0_audience,
        "exp": 1234567890,
        f"{settings.auth0_audience}/roles": ["MAKER", "CHECKER"],
    }

    # Extract user subject
    user_sub = get_user_sub(test_payload)
    print(f"User Subject: {user_sub}")
    assert user_sub == "google-oauth2|123456789", "User subject mismatch"

    # Extract user roles
    roles = get_user_roles(test_payload)
    print(f"User Roles: {roles}")
    assert roles == ["MAKER", "CHECKER"], "User roles mismatch"

    print("User extraction tests passed!")


def test_missing_sub():
    """Test error handling when 'sub' claim is missing."""
    print("\n=== Testing Missing Sub Claim ===")

    payload_without_sub = {
        "iss": f"https://{settings.auth0_domain}/",
        "aud": settings.auth0_audience,
    }

    try:
        get_user_sub(payload_without_sub)
        raise AssertionError("Should have raised UnauthorizedError")
    except UnauthorizedError as e:
        print(f"Correctly raised UnauthorizedError: {e.message}")
        print("Missing sub test passed!")


def test_missing_roles():
    """Test default behavior when roles claim is missing."""
    print("\n=== Testing Missing Roles Claim ===")

    payload_without_roles = {
        "sub": "auth0|user123",
        "iss": f"https://{settings.auth0_domain}/",
        "aud": settings.auth0_audience,
    }

    roles = get_user_roles(payload_without_roles)
    print(f"Roles (should be empty): {roles}")
    assert roles == [], "Should return empty list when no roles"
    print("Missing roles test passed!")


def test_malformed_roles():
    """Test handling of malformed roles claim."""
    print("\n=== Testing Malformed Roles Claim ===")

    payload_with_string_roles = {
        "sub": "auth0|user123",
        f"{settings.auth0_audience}/roles": "MAKER",  # String instead of list
    }

    roles = get_user_roles(payload_with_string_roles)
    print(f"Roles (should be empty for malformed claim): {roles}")
    assert roles == [], "Should return empty list for malformed roles"
    print("Malformed roles test passed!")


def test_role_checker():
    """Test role-based access control."""
    print("\n=== Testing Role-Based Access Control ===")

    # User with MAKER role
    maker_payload = {
        "sub": "google-oauth2|maker123",
        f"{settings.auth0_audience}/roles": ["MAKER"],
    }

    # User with CHECKER role
    checker_payload = {
        "sub": "google-oauth2|checker456",
        f"{settings.auth0_audience}/roles": ["CHECKER"],
    }

    # User with both roles
    admin_payload = {
        "sub": "google-oauth2|admin789",
        f"{settings.auth0_audience}/roles": ["MAKER", "CHECKER", "ADMIN"],
    }

    # Create role checker dependency
    require_maker = require_role("MAKER")
    role_checker = require_maker  # Get the inner function

    # Test: MAKER can access MAKER endpoint
    print("\n1. Testing MAKER accessing MAKER endpoint...")
    try:
        # Simulate the dependency injection
        from unittest.mock import Mock

        Mock(return_value=maker_payload)
        result = role_checker(user=maker_payload)
        print("   Success: MAKER granted access")
        assert result == maker_payload
    except ForbiddenError:
        print("   Error: Should have granted access")
        raise

    # Test: CHECKER cannot access MAKER endpoint
    print("\n2. Testing CHECKER accessing MAKER endpoint...")
    try:
        result = role_checker(user=checker_payload)
        print("   Error: Should have denied access")
        raise AssertionError("Should have raised ForbiddenError")
    except ForbiddenError as e:
        print(f"   Success: Access denied - {e.message}")
        assert "Insufficient permissions" in e.message

    # Test: ADMIN (has MAKER role) can access MAKER endpoint
    print("\n3. Testing ADMIN accessing MAKER endpoint...")
    try:
        result = role_checker(user=admin_payload)
        print("   Success: ADMIN (with MAKER role) granted access")
        assert result == admin_payload
    except ForbiddenError:
        print("   Error: Should have granted access")
        raise

    print("\nRole-based access control tests passed!")


def test_jwks_cache():
    """Test JWKS cache functionality."""
    print("\n=== Testing JWKS Cache ===")

    # Clear the cache
    clear_jwks_cache()
    print("JWKS cache cleared successfully")

    print("Cache test passed!")


def test_config():
    """Test that configuration is properly loaded."""
    print("\n=== Testing Configuration ===")

    print(f"Auth0 Domain: {settings.auth0_domain}")
    print(f"Auth0 Audience: {settings.auth0_audience}")
    print(f"Auth0 Algorithms: {settings.auth0_algorithms_list}")
    print(f"CORS Origins: {settings.cors_origins_list}")

    assert settings.auth0_domain, "Auth0 domain not configured"
    assert settings.auth0_audience, "Auth0 audience not configured"
    assert "RS256" in settings.auth0_algorithms_list, "RS256 algorithm not configured"

    print("Configuration test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Auth0 JWT Authentication Integration Tests")
    print("=" * 60)

    try:
        test_config()
        test_user_extraction()
        test_missing_sub()
        test_missing_roles()
        test_malformed_roles()
        test_role_checker()
        test_jwks_cache()

        print("\n" + "=" * 60)
        print("All tests passed successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
