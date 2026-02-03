"""
Tests for JWKS cache functionality.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.security.circuit_breaker import CircuitBreaker, CircuitBreakerState
from app.core.security.jwks_cache import JWKSCache


class TestJWKSCache:
    @pytest.mark.anyio
    async def test_get_jwks_caches_response(self):
        cache = JWKSCache(ttl_seconds=3600)
        mock_response = {"keys": [{"kid": "test", "kty": "RSA"}]}

        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response

            result1 = cache.get_jwks()
            assert result1 == mock_response
            assert mock_get.call_count == 1

            result2 = cache.get_jwks()
            assert result2 == mock_response
            assert mock_get.call_count == 1

    @pytest.mark.anyio
    async def test_get_jwks_fallback_to_stale_cache_on_error(self):
        cache = JWKSCache(ttl_seconds=1)
        mock_response = {"keys": [{"kid": "test"}]}

        with patch("httpx.Client.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            cache.get_jwks()

            import time

            time.sleep(2)
            mock_get.side_effect = httpx.ConnectError("Network error")

            result = cache.get_jwks()
            assert result == mock_response

    @pytest.mark.anyio
    async def test_clear_cache(self):
        cache = JWKSCache()
        cache._cache = {"test": "data"}
        cache.clear()
        assert cache._cache is None

    @pytest.mark.anyio
    async def test_jwks_cache_has_circuit_breaker(self):
        cache = JWKSCache()
        assert hasattr(cache, "_circuit_breaker")
        assert isinstance(cache._circuit_breaker, CircuitBreaker)

    @pytest.mark.anyio
    async def test_jwks_cache_clear_resets_circuit_breaker(self):
        cache = JWKSCache()

        for _ in range(5):
            try:

                def raise_request_error() -> None:
                    raise httpx.RequestError("Test")

                cache._circuit_breaker.call(raise_request_error)
            except httpx.RequestError:
                pass

        assert cache._circuit_breaker.is_open

        cache.clear()
        assert cache._circuit_breaker.state == CircuitBreakerState.CLOSED
        assert cache._circuit_breaker.failure_count == 0

    @pytest.mark.anyio
    async def test_jwks_cache_uses_circuit_breaker_on_sync_fetch(self):
        cache = JWKSCache(ttl_seconds=0)

        with patch("httpx.Client.get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("Network error")

            for _ in range(5):
                with pytest.raises(Exception):
                    cache.get_jwks()

            assert cache._circuit_breaker.is_open

            call_count = [0]

            def side_effect(*args, **kwargs):
                call_count[0] += 1
                raise httpx.ConnectError("Should not be called")

            mock_get.side_effect = side_effect

            with pytest.raises(Exception):
                cache.get_jwks()

            assert call_count[0] == 0

    @pytest.mark.anyio
    async def test_jwks_cache_fallback_to_stale_when_circuit_open(self):
        cache = JWKSCache(ttl_seconds=0)

        stale_response = {"keys": [{"kid": "stale", "kty": "RSA"}]}

        with patch("httpx.Client.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.return_value = stale_response
            mock_response.raise_for_status = lambda: None

            result1 = cache.get_jwks()
            assert result1 == stale_response

            mock_get.side_effect = httpx.ConnectError("Network error")

            for _ in range(5):
                try:
                    cache.get_jwks()
                except Exception:
                    pass

            assert cache._circuit_breaker.is_open

            result2 = cache.get_jwks()
            assert result2 == stale_response

    @pytest.mark.anyio
    async def test_jwks_cache_error_response(self):
        cache = JWKSCache(ttl_seconds=3600)

        with patch("httpx.Client.get") as mock_get:
            mock_response = mock_get.return_value
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Error", request=MagicMock(), response=MagicMock(status_code=500)
            )

            with pytest.raises(Exception):
                cache.get_jwks()

    @pytest.mark.anyio
    async def test_jwks_cache_ttl_expiration(self):
        import time

        cache = JWKSCache(ttl_seconds=1)

        with patch("httpx.Client.get") as mock_get:
            mock_response = {"keys": [{"kid": "test", "kty": "RSA"}]}
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status = lambda: None

            result1 = cache.get_jwks()
            assert result1 == mock_response

            time.sleep(1.5)

            result2 = cache.get_jwks()
            assert result2 == mock_response
            assert mock_get.call_count == 2


class TestJWKSCacheEdgeCases:
    @pytest.mark.anyio
    async def test_cache_valid_with_none_cache(self):
        cache = JWKSCache()
        cache._cache = None
        cache._cache_time = None

        now = datetime.now(UTC)
        assert cache._is_cache_valid(now) is False

    @pytest.mark.anyio
    async def test_cache_valid_with_expired_cache(self):
        cache = JWKSCache(ttl_seconds=60)
        cache._cache = {"keys": []}
        cache._cache_time = datetime.now(UTC) - timedelta(seconds=120)

        now = datetime.now(UTC)
        assert cache._is_cache_valid(now) is False

    @pytest.mark.anyio
    async def test_use_stale_cache_when_available(self):
        cache = JWKSCache()
        cache._cache = {"keys": [{"kid": "stale"}]}

        result = cache._use_stale_cache_if_available("test reason")
        assert result == cache._cache

    @pytest.mark.anyio
    async def test_use_stale_cache_when_not_available(self):
        cache = JWKSCache()
        cache._cache = None

        result = cache._use_stale_cache_if_available("test reason")
        assert result is None

    @pytest.mark.anyio
    async def test_handle_fetch_error_circuit_breaker_open_with_cache(self):
        cache = JWKSCache()
        cache._cache = {"keys": [{"kid": "stale"}]}

        error = RuntimeError("Circuit breaker is OPEN")
        result = cache._handle_fetch_error(error)

        assert result == cache._cache

    @pytest.mark.anyio
    async def test_handle_fetch_error_circuit_breaker_open_without_cache(self):
        from app.core.errors import UnauthorizedError

        cache = JWKSCache()
        cache._cache = None

        error = RuntimeError("Circuit breaker is OPEN")
        with pytest.raises(UnauthorizedError) as exc_info:
            cache._handle_fetch_error(error)

        assert "circuit open" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_handle_fetch_error_generic_with_stale_cache(self):
        cache = JWKSCache()
        cache._cache = {"keys": [{"kid": "stale"}]}

        error = httpx.ConnectError("Network error")
        result = cache._handle_fetch_error(error)

        assert result == cache._cache

    @pytest.mark.anyio
    async def test_handle_fetch_error_generic_without_stale_cache(self):
        from app.core.errors import UnauthorizedError

        cache = JWKSCache()
        cache._cache = None

        error = httpx.ConnectError("Network error")
        with pytest.raises(UnauthorizedError) as exc_info:
            cache._handle_fetch_error(error)

        assert "authentication service unavailable" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_check_circuit_breaker_when_open_with_cache(self):
        cache = JWKSCache()
        cache._cache = {"keys": [{"kid": "cached"}]}
        cache._circuit_breaker._state = CircuitBreakerState.OPEN

        now = datetime.now(UTC)
        result = cache._check_circuit_breaker(now)

        assert result == cache._cache

    @pytest.mark.anyio
    async def test_check_circuit_breaker_when_closed(self):
        cache = JWKSCache()
        cache._cache = {"keys": [{"kid": "cached"}]}
        cache._circuit_breaker._state = CircuitBreakerState.CLOSED

        now = datetime.now(UTC)
        result = cache._check_circuit_breaker(now)

        assert result is None

    @pytest.mark.anyio
    async def test_check_circuit_breaker_when_open_no_cache(self):
        cache = JWKSCache()
        cache._cache = None
        cache._circuit_breaker._state = CircuitBreakerState.OPEN

        now = datetime.now(UTC)
        result = cache._check_circuit_breaker(now)

        assert result is None

    @pytest.mark.anyio
    async def test_get_jwks_async_with_valid_cache(self):
        cache = JWKSCache(ttl_seconds=60)
        cache._cache = {"keys": [{"kid": "cached"}]}
        cache._cache_time = datetime.now(UTC)

        result = await cache.get_jwks_async()
        assert result == cache._cache

    @pytest.mark.anyio
    async def test_get_jwks_async_with_expired_cache(self):
        cache = JWKSCache(ttl_seconds=0)

        async def mock_get(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.json.return_value = {"keys": [{"kid": "fresh"}]}
            mock_response.raise_for_status = lambda: None
            return mock_response

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("app.core.security.jwks_cache.get_async_http_client") as mock_get_client:
            mock_get_client.return_value = mock_client

            result = await cache.get_jwks_async()
            assert result == {"keys": [{"kid": "fresh"}]}

    @pytest.mark.anyio
    async def test_get_jwks_async_handles_error_with_stale_cache(self):
        cache = JWKSCache(ttl_seconds=0)
        cache._cache = {"keys": [{"kid": "stale"}]}
        cache._cache_time = datetime.now(UTC)

        async def mock_get_error(*args, **kwargs):
            raise httpx.ConnectError("Network error")

        mock_client = MagicMock()
        mock_client.get = mock_get_error

        with patch("app.core.security.jwks_cache.get_async_http_client") as mock_get_client:
            mock_get_client.return_value = mock_client

            result = await cache.get_jwks_async()
            assert result == cache._cache


class TestAsyncHttpClient:
    @pytest.mark.anyio
    async def test_get_async_http_client_creates_singleton(self):
        # Set _async_http to None for testing
        import app.core.security.jwks_cache as jwks_module
        from app.core.security.jwks_cache import get_async_http_client

        jwks_module._async_http = None

        client1 = get_async_http_client()
        client2 = get_async_http_client()

        assert client1 is client2
        assert isinstance(client1, httpx.AsyncClient)

    @pytest.mark.anyio
    async def test_close_async_http_client(self):
        # Set _async_http to None for testing
        import app.core.security.jwks_cache as jwks_module
        from app.core.security.jwks_cache import (
            close_async_http_client,
            get_async_http_client,
        )

        jwks_module._async_http = None

        client = get_async_http_client()
        assert client is not None

        await close_async_http_client()

    @pytest.mark.anyio
    async def test_close_async_http_client_when_none(self):
        # Set _async_http to None for testing
        import app.core.security.jwks_cache as jwks_module
        from app.core.security.jwks_cache import close_async_http_client

        jwks_module._async_http = None

        await close_async_http_client()
