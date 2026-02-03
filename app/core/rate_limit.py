"""Rate limiting middleware for FastAPI application."""

import logging
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# SECURITY WARNING: In-memory rate limiting does NOT work in distributed deployments.
# When running multiple pods/replicas, each instance maintains its own rate limit state,
# allowing attackers to bypass limits by distributing requests across instances.
#
# For production deployments with multiple workers/pods, implement Redis-based rate limiting:
#
# ```python
# class RedisRateLimiter:
#     def is_allowed(self, identifier: str, endpoint: str, limit: int, window: int) -> bool:
#         key = f"ratelimit:{identifier}:{endpoint}"
#         current = redis.incr(key)
#         if current == 1:
#             redis.expire(key, window)
#         return current <= limit
# ```


class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window algorithm.

    For production, use Redis-backed rate limiter for distributed systems.
    """

    def __init__(self):
        """Initialize in-memory storage for rate limit tracking."""
        # Key: (identifier, endpoint), Value: list of timestamps
        self._requests: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
        self._cleanup_interval = 300  # Clean up old data every 5 minutes
        self._last_cleanup = time.time()

    def _cleanup_old_entries(self, now: float) -> None:
        """Remove entries older than 1 hour to prevent memory leaks."""
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        cutoff = now - 3600  # 1 hour ago

        # Clean up old entries
        keys_to_delete = []
        for key, timestamps in self._requests.items():
            # Filter out old timestamps
            self._requests[key] = [t for t in timestamps if t > cutoff]
            if not self._requests[key]:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._requests[key]

        if keys_to_delete:
            logger.debug(f"Cleaned up {len(keys_to_delete)} expired rate limit entries")

    def is_allowed(self, identifier: str, endpoint: str, limit: int, window: int) -> bool:
        """
        Check if request is allowed under rate limit.

        Args:
            identifier: Unique identifier (user_id or IP)
            endpoint: Endpoint path
            limit: Max requests allowed
            window: Time window in seconds

        Returns:
            True if request is allowed, False otherwise
        """
        now = time.time()
        self._cleanup_old_entries(now)

        key = (identifier, endpoint)
        timestamps = self._requests[key]

        # Remove timestamps outside the current window
        window_start = now - window
        recent_requests = [t for t in timestamps if t > window_start]

        # Check if limit exceeded
        if len(recent_requests) >= limit:
            return False

        # Add current request
        recent_requests.append(now)
        self._requests[key] = recent_requests

        return True

    def get_remaining_count(self, identifier: str, endpoint: str, limit: int, window: int) -> int:
        """
        Get remaining request count for rate limit.

        Args:
            identifier: Unique identifier (user_id or IP)
            endpoint: Endpoint path
            limit: Max requests allowed
            window: Time window in seconds

        Returns:
            Number of requests remaining
        """
        now = time.time()
        key = (identifier, endpoint)
        timestamps = self._requests[key]

        window_start = now - window
        recent_count = len([t for t in timestamps if t > window_start])

        return max(0, limit - recent_count)

    def reset(self) -> None:
        """
        Reset all rate limit state.

        Used primarily in tests to clear rate limiting between test cases.
        """
        self._requests.clear()
        self._last_cleanup = time.time()


# Global rate limiter instance
_rate_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for FastAPI.

    Applies rate limits based on endpoint and user identity.
    """

    # Default rate limits (requests per window)
    DEFAULT_LIMITS = {
        # High-risk operations (write operations)
        "POST:/api/v1/rules": (60, 60),  # 60/minute
        "POST:/api/v1/rulesets": (30, 60),  # 30/minute
        "POST:/api/v1/rule-versions": (60, 60),  # 60/minute
        "POST:/api/v1/": (100, 60),  # 100/minute for other POST
        # Read operations
        "GET:/api/v1/rules": (200, 60),  # 200/minute
        "GET:/api/v1/rulesets": (200, 60),  # 200/minute
        "GET:/api/v1/audit-log": (100, 60),  # 100/minute
        "GET:/api/v1/": (500, 60),  # 500/minute for other GET
    }

    def __init__(self, app, limiter: InMemoryRateLimiter | None = None):
        """
        Initialize rate limit middleware.

        Args:
            app: FastAPI application
            limiter: Rate limiter instance (uses global if None)
        """
        super().__init__(app)
        self.limiter = limiter or get_rate_limiter()

    def _get_rate_limit(self, method: str, path: str) -> tuple[int, int]:
        """
        Get rate limit for an endpoint.

        Args:
            method: HTTP method
            path: Request path

        Returns:
            Tuple of (limit, window_seconds)
        """
        key = f"{method}:{path}"

        # Try exact match first
        if key in self.DEFAULT_LIMITS:
            return self.DEFAULT_LIMITS[key]

        # Try prefix match for generic limits
        generic_key = f"{method}:/"
        if generic_key in self.DEFAULT_LIMITS:
            return self.DEFAULT_LIMITS[generic_key]

        # Default: 1000 requests per hour
        return (1000, 3600)

    def _get_identifier(self, request: Request) -> str:
        """
        Get identifier for rate limiting.

        Prioritizes user_id over IP address for per-user limits.

        Args:
            request: Incoming request

        Returns:
            Identifier string
        """
        # Try to get user_id from authenticated user
        if hasattr(request.state, "user"):
            user = request.state.user
            if isinstance(user, dict) and "sub" in user:
                return f"user:{user['sub']}"

        # Fall back to IP address
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and enforce rate limits.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response or 429 error if rate limited
        """
        from app.core.config import settings

        # Skip rate limiting entirely in test environments
        # Tests simulate controlled scenarios and should not be rate limited
        if settings.app_env == "test":
            return await call_next(request)

        # Skip rate limiting for health endpoints
        if request.url.path in [
            "/api/v1/health",
            "/api/v1/readyz",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]:
            return await call_next(request)

        # SECURITY: Only bypass rate limiting for localhost in local (non-test) environments.
        # In production, localhost bypasses are disabled to prevent header spoofing attacks.
        # Bypass is only allowed for exact IP matches (not substring matching).
        if settings.app_env == "local":
            client_host = request.client.host if request.client else ""
            # Exact match only - no substring matching to prevent bypass
            if client_host in ("127.0.0.1", "::1", "localhost"):
                return await call_next(request)

        method = request.method
        path = request.url.path

        # Get rate limit for this endpoint
        limit, window = self._get_rate_limit(method, path)

        # Get identifier (user_id or IP)
        identifier = self._get_identifier(request)

        # Check if allowed
        if not self.limiter.is_allowed(identifier, path, limit, window):
            remaining = 0
            reset_time = int(time.time() + window)

            logger.warning(
                f"Rate limit exceeded for {identifier} on {method} {path}",
                extra={
                    "identifier": identifier,
                    "method": method,
                    "path": path,
                    "limit": limit,
                    "window": window,
                },
            )

            response = Response(
                content=f'{{"error":"RateLimitExceeded","message":"Rate limit exceeded","limit":{limit},"window":{window}}}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
            )
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Reset"] = str(reset_time)
            return response

        # Get remaining count and add to response headers
        remaining = self.limiter.get_remaining_count(identifier, path, limit, window)
        reset_time = int(time.time() + window)

        response = await call_next(request)

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)

        return response
