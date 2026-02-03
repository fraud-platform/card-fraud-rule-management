"""
Tests for rate limiting middleware.

Tests cover:
- InMemoryRateLimiter class functionality
- Rate limit configuration
- Different limits per endpoint
- IP-based vs user-based limiting
- Sliding window calculation
"""

from unittest.mock import MagicMock

import pytest

from app.core.rate_limit import (
    InMemoryRateLimiter,
    RateLimitMiddleware,
    get_rate_limiter,
)


class TestInMemoryRateLimiter:
    """Tests for the InMemoryRateLimiter class."""

    @pytest.mark.anyio
    async def test_is_allowed_within_limit(self):
        """Test that requests within limit are allowed."""
        limiter = InMemoryRateLimiter()
        identifier = "user:test-user"
        endpoint = "/api/v1/rules"
        limit = 5
        window = 60

        # First request should be allowed
        assert limiter.is_allowed(identifier, endpoint, limit, window) is True

        # Second request should also be allowed
        assert limiter.is_allowed(identifier, endpoint, limit, window) is True

    @pytest.mark.anyio
    async def test_is_allowed_exceeds_limit(self):
        """Test that requests exceeding limit are blocked."""
        limiter = InMemoryRateLimiter()
        identifier = "user:test-user"
        endpoint = "/api/v1/rules"
        limit = 3
        window = 60

        # First 3 requests should be allowed
        for _ in range(3):
            assert limiter.is_allowed(identifier, endpoint, limit, window) is True

        # 4th request should be blocked
        assert limiter.is_allowed(identifier, endpoint, limit, window) is False

    @pytest.mark.anyio
    async def test_different_identifiers_tracked_separately(self):
        """Test that different users/IPs have separate rate limits."""
        limiter = InMemoryRateLimiter()
        limit = 2
        window = 60

        # User 1 makes 2 requests
        assert limiter.is_allowed("user:user1", "/api/v1/rules", limit, window) is True
        assert limiter.is_allowed("user:user1", "/api/v1/rules", limit, window) is True
        assert limiter.is_allowed("user:user1", "/api/v1/rules", limit, window) is False

        # User 2 should still be able to make requests
        assert limiter.is_allowed("user:user2", "/api/v1/rules", limit, window) is True
        assert limiter.is_allowed("user:user2", "/api/v1/rules", limit, window) is True

    @pytest.mark.anyio
    async def test_different_endpoints_tracked_separately(self):
        """Test that rate limits are per endpoint."""
        limiter = InMemoryRateLimiter()
        identifier = "user:test-user"
        limit = 2
        window = 60

        # Exhaust limit on /api/v1/rules
        assert limiter.is_allowed(identifier, "/api/v1/rules", limit, window) is True
        assert limiter.is_allowed(identifier, "/api/v1/rules", limit, window) is True
        assert limiter.is_allowed(identifier, "/api/v1/rules", limit, window) is False

        # Should still have full quota on /api/v1/rulesets
        assert limiter.is_allowed(identifier, "/api/v1/rulesets", limit, window) is True
        assert limiter.is_allowed(identifier, "/api/v1/rulesets", limit, window) is True

    @pytest.mark.anyio
    async def test_get_remaining_count(self):
        """Test getting remaining request count."""
        limiter = InMemoryRateLimiter()
        identifier = "user:test-user"
        endpoint = "/api/v1/rules"
        limit = 5
        window = 60

        # Initially should have full quota
        assert limiter.get_remaining_count(identifier, endpoint, limit, window) == 5

        # After 1 request
        limiter.is_allowed(identifier, endpoint, limit, window)
        assert limiter.get_remaining_count(identifier, endpoint, limit, window) == 4

        # After 2 more requests
        limiter.is_allowed(identifier, endpoint, limit, window)
        limiter.is_allowed(identifier, endpoint, limit, window)
        assert limiter.get_remaining_count(identifier, endpoint, limit, window) == 2


class TestRateLimitMiddleware:
    """Tests for the RateLimitMiddleware middleware."""

    @pytest.mark.anyio
    async def test_get_rate_limit_exact_match(self):
        """Test getting rate limit for exact endpoint match."""
        middleware = RateLimitMiddleware(app=None)

        limit, window = middleware._get_rate_limit("POST", "/api/v1/rules")
        assert limit == 60
        assert window == 60

    @pytest.mark.anyio
    async def test_get_rate_limit_for_rulesets(self):
        """Test getting rate limit for rulesets endpoint."""
        middleware = RateLimitMiddleware(app=None)

        limit, window = middleware._get_rate_limit("POST", "/api/v1/rulesets")
        assert limit == 30
        assert window == 60

    @pytest.mark.anyio
    async def test_get_rate_limit_for_get_rules(self):
        """Test getting rate limit for GET rules endpoint."""
        middleware = RateLimitMiddleware(app=None)

        limit, window = middleware._get_rate_limit("GET", "/api/v1/rules")
        assert limit == 200
        assert window == 60

    @pytest.mark.anyio
    async def test_get_rate_limit_generic_fallback(self):
        """Test getting rate limit falls back to generic POST limit."""
        middleware = RateLimitMiddleware(app=None)

        # Endpoint not in specific list should get default limit
        # The generic POST:/ limit is for POST:/api/v1/ prefix only
        # Unknown endpoints fall through to the default
        limit, window = middleware._get_rate_limit("POST", "/api/v1/unknown")
        assert limit == 1000  # Default limit
        assert window == 3600

    @pytest.mark.anyio
    async def test_get_rate_limit_default_fallback(self):
        """Test getting rate limit falls back to default."""
        middleware = RateLimitMiddleware(app=None)

        # PUT not in any list should get default
        limit, window = middleware._get_rate_limit("PUT", "/api/v1/something")
        assert limit == 1000
        assert window == 3600

    @pytest.mark.anyio
    async def test_get_identifier_uses_user_id(self):
        """Test that user_id is prioritized over IP for rate limiting."""
        middleware = RateLimitMiddleware(app=None)

        request = MagicMock()
        mock_user = {"sub": "auth0|123456"}
        request.state.user = mock_user

        identifier = middleware._get_identifier(request)
        assert identifier == "user:auth0|123456"

    @pytest.mark.anyio
    async def test_get_identifier_falls_back_to_ip(self):
        """Test that IP address is used when user is not available."""
        middleware = RateLimitMiddleware(app=None)

        request = MagicMock()
        request.state = MagicMock()
        # Simulate missing user attribute
        request.state.user = None
        request.client.host = "192.168.1.100"

        identifier = middleware._get_identifier(request)
        assert identifier == "ip:192.168.1.100"

    @pytest.mark.anyio
    async def test_get_identifier_handles_missing_client(self):
        """Test that 'unknown' is used when client is not available."""
        middleware = RateLimitMiddleware(app=None)

        request = MagicMock()
        request.state = MagicMock()
        request.state.user = None
        request.client = None

        identifier = middleware._get_identifier(request)
        assert identifier == "ip:unknown"


class TestRateLimitIntegration:
    """Integration tests for rate limiting with real InMemoryRateLimiter."""

    @pytest.mark.anyio
    async def test_full_rate_limit_cycle(self):
        """Test a complete rate limit cycle with real limiter."""
        limiter = InMemoryRateLimiter()
        middleware = RateLimitMiddleware(app=None, limiter=limiter)

        # Simulate multiple requests from same user
        identifier = "user:test-user"
        endpoint = "/api/v1/rules"
        limit, window = middleware._get_rate_limit("POST", endpoint)

        # First request should pass
        assert limiter.is_allowed(identifier, endpoint, limit, window) is True

        # Make remaining requests up to limit
        for _ in range(limit - 1):
            assert limiter.is_allowed(identifier, endpoint, limit, window) is True

        # Next request should be rate limited
        assert limiter.is_allowed(identifier, endpoint, limit, window) is False

        # Remaining count should be 0
        assert limiter.get_remaining_count(identifier, endpoint, limit, window) == 0


class TestGetRateLimiter:
    """Tests for the get_rate_limiter function."""

    @pytest.mark.anyio
    async def test_get_rate_limiter_returns_singleton(self):
        """Test that get_rate_limiter returns the same instance."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is limiter2
        assert isinstance(limiter1, InMemoryRateLimiter)


class TestInMemoryRateLimiterCleanup:
    """Tests for the cleanup functionality in InMemoryRateLimiter."""

    @pytest.mark.anyio
    async def test_cleanup_old_entries_skips_when_not_needed(self):
        """Test that cleanup is skipped when cleanup interval hasn't passed."""
        import time

        limiter = InMemoryRateLimiter()
        # Set last_cleanup to recent time
        limiter._last_cleanup = time.time()

        # Add some old entries
        limiter._requests[("user:test", "/api/v1/test")] = [time.time() - 7200]  # 2 hours ago

        # Cleanup should be skipped (not enough time passed)
        limiter._cleanup_old_entries(time.time())

        # Old entry should still be there
        assert limiter._requests[("user:test", "/api/v1/test")]

    @pytest.mark.anyio
    async def test_reset_clears_all_state(self):
        """Test that reset() clears all rate limit state."""
        limiter = InMemoryRateLimiter()

        # Add some entries
        limiter.is_allowed("user:test1", "/api/v1/test1", 5, 60)
        limiter.is_allowed("user:test2", "/api/v1/test2", 5, 60)

        assert len(limiter._requests) > 0

        # Reset
        limiter.reset()

        # All state should be cleared
        assert len(limiter._requests) == 0
