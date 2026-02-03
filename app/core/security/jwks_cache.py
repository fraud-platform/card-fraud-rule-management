"""
JWKS cache with TTL support for Auth0 token verification.

Caches the JWKS response to avoid fetching it on every token verification.
Keys are automatically refreshed when the cache expires (default 1 hour).

Includes circuit breaker pattern to handle JWKS fetch failures gracefully.
"""

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import UnauthorizedError

from .circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

_async_http: httpx.AsyncClient | None = None
_http = httpx.Client(timeout=httpx.Timeout(10.0))


def get_async_http_client() -> httpx.AsyncClient:
    """Get or create the async HTTP client singleton."""
    global _async_http
    if _async_http is None:
        _async_http = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _async_http


async def close_async_http_client() -> None:
    """Close the async HTTP client (for graceful shutdown)."""
    global _async_http
    if _async_http is not None:
        await _async_http.aclose()
        _async_http = None


class JWKSCache:
    """
    In-memory cache for Auth0 JWKS with time-to-live (TTL) support.

    Caches the JWKS response to avoid fetching it on every token verification.
    Keys are automatically refreshed when the cache expires (default 1 hour).

    Includes circuit breaker pattern to handle JWKS fetch failures gracefully.

    Supports both sync and async fetching for backward compatibility.
    """

    def __init__(self, ttl_seconds: int = 3600):
        """
        Initialize the JWKS cache.

        Args:
            ttl_seconds: Time-to-live for cached keys in seconds (default 1 hour)
        """
        self._cache: dict[str, Any] | None = None
        self._cache_time: datetime | None = None
        self._ttl_seconds = ttl_seconds
        self._jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        self._circuit_breaker = CircuitBreaker()

    def _is_cache_valid(self, now: datetime) -> bool:
        """Check if cached JWKS is still valid (within TTL)."""
        return (
            self._cache is not None
            and self._cache_time is not None
            and now - self._cache_time < timedelta(seconds=self._ttl_seconds)
        )

    def _use_stale_cache_if_available(self, reason: str) -> dict[str, Any] | None:
        """Log and return stale cache if available, otherwise return None."""
        if self._cache is not None:
            logger.warning(f"Using stale JWKS cache as fallback ({reason})")
            return self._cache
        return None

    def _handle_fetch_error(self, error: Exception) -> dict[str, Any] | None:
        """Handle JWKS fetch errors with stale cache fallback."""
        if "Circuit breaker is OPEN" in str(error):
            logger.error("Circuit breaker prevented JWKS fetch")
            stale = self._use_stale_cache_if_available("circuit open")
            if stale:
                return stale
            raise UnauthorizedError(
                "Unable to verify token: authentication service unavailable (circuit open)"
            )

        logger.error(f"Failed to fetch JWKS: {error}")
        logger.info(
            f"Circuit breaker state: {self._circuit_breaker.state.value}, "
            f"failures: {self._circuit_breaker.failure_count}"
        )

        stale = self._use_stale_cache_if_available("fetch failed")
        if stale:
            return stale

        raise UnauthorizedError("Unable to verify token: authentication service unavailable")

    def _check_circuit_breaker(self, now: datetime) -> dict[str, Any] | None:
        """Check circuit breaker and use stale cache if open."""
        if self._circuit_breaker.is_open and self._cache is not None:
            logger.warning(
                f"Circuit breaker is OPEN - using stale JWKS cache. "
                f"State: {self._circuit_breaker.state.value}, "
                f"Failures: {self._circuit_breaker.failure_count}"
            )
            return self._cache
        return None

    def _log_cache_refreshed(self) -> None:
        """Log successful cache refresh."""
        logger.info(
            f"JWKS cache refreshed successfully. Circuit state: {self._circuit_breaker.state.value}"
        )

    def _log_fetch_attempt(self) -> None:
        """Log JWKS fetch attempt."""
        logger.info(f"Fetching JWKS from {self._jwks_url}")

    async def get_jwks_async(self) -> dict[str, Any]:
        """
        Get JWKS from cache or fetch from Auth0 (async version).

        Uses circuit breaker pattern to handle fetch failures gracefully.

        Returns:
            JWKS dictionary containing signing keys

        Raises:
            UnauthorizedError: If JWKS fetch fails and no cache available
        """
        now = datetime.now(UTC)

        async with self._async_lock:
            if self._is_cache_valid(now):
                logger.debug("Using cached JWKS")
                return self._cache

            cached = self._check_circuit_breaker(now)
            if cached:
                return cached

            try:
                self._log_fetch_attempt()
                client = get_async_http_client()

                async def _fetch():
                    response = await client.get(self._jwks_url)
                    response.raise_for_status()
                    return response.json()

                self._cache = await self._circuit_breaker.call_async(_fetch())
                self._cache_time = now
                self._log_cache_refreshed()
                return self._cache

            except Exception as e:
                cached = self._handle_fetch_error(e)
                if cached:
                    return cached
                raise

    def get_jwks(self) -> dict[str, Any]:
        """
        Get JWKS from cache or fetch from Auth0 (sync version).

        This is a legacy method for backward compatibility.
        New code should use get_jwks_async().

        Uses circuit breaker pattern to handle fetch failures gracefully.

        Returns:
            JWKS dictionary containing signing keys

        Raises:
            UnauthorizedError: If JWKS fetch fails and no cache available
        """
        now = datetime.now(UTC)

        with self._lock:
            if self._is_cache_valid(now):
                logger.debug("Using cached JWKS")
                return self._cache

            cached = self._check_circuit_breaker(now)
            if cached:
                return cached

            try:
                self._log_fetch_attempt()

                def _fetch():
                    response = _http.get(self._jwks_url)
                    response.raise_for_status()
                    return response.json()

                self._cache = self._circuit_breaker.call(_fetch)
                self._cache_time = now
                self._log_cache_refreshed()
                return self._cache

            except Exception as e:
                cached = self._handle_fetch_error(e)
                if cached:
                    return cached
                raise

    def clear(self) -> None:
        """Clear the JWKS cache and reset circuit breaker (useful for testing)."""
        with self._lock:
            self._cache = None
            self._cache_time = None
            self._circuit_breaker.reset()
        logger.debug("JWKS cache and circuit breaker cleared")


_jwks_cache = JWKSCache()


def get_jwks() -> dict[str, Any]:
    """
    Fetch Auth0's JSON Web Key Set (JWKS) for token verification (sync version).

    The JWKS contains the public keys used to verify JWT signatures.
    This function uses a TTL-based cache to avoid repeated network calls.

    Returns:
        JWKS dictionary containing public keys

    Raises:
        UnauthorizedError: If JWKS endpoint is unreachable
    """
    return _jwks_cache.get_jwks()


async def get_jwks_async() -> dict[str, Any]:
    """
    Fetch Auth0's JSON Web Key Set (JWKS) for token verification (async version).

    The JWKS contains the public keys used to verify JWT signatures.
    This function uses a TTL-based cache to avoid repeated network calls.

    Returns:
        JWKS dictionary containing public keys

    Raises:
        UnauthorizedError: If JWKS endpoint is unreachable
    """
    return await _jwks_cache.get_jwks_async()


def clear_jwks_cache() -> None:
    """
    Clear the JWKS cache.

    Useful for testing or forcing a refresh of signing keys.
    The cache will be automatically refreshed on the next token verification.
    """
    _jwks_cache.clear()
    logger.info("JWKS cache cleared")
