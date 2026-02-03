"""
Tests for circuit breaker pattern.
"""

import asyncio

import httpx
import pytest

from app.core.security.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
)


class TestCircuitBreaker:
    @pytest.mark.anyio
    async def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert not cb.is_open

    @pytest.mark.anyio
    async def test_success_keeps_circuit_closed(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def success_func():
            return "success"

        result = cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.anyio
    async def test_failures_increment_counter(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Network error")

        with pytest.raises(httpx.RequestError):
            cb.call(failing_func)
        assert cb.failure_count == 1
        assert cb.state == CircuitBreakerState.CLOSED

        with pytest.raises(httpx.RequestError):
            cb.call(failing_func)
        assert cb.failure_count == 2
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.anyio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Network error")

        for _ in range(3):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open
        assert cb.failure_count == 3

    @pytest.mark.anyio
    async def test_fails_fast_when_open(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Network error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.is_open

        call_count = [0]

        def should_not_be_called():
            call_count[0] += 1
            return "should not execute"

        with pytest.raises(Exception) as exc_info:
            cb.call(should_not_be_called)

        assert "Circuit breaker is OPEN" in str(exc_info.value)
        assert call_count[0] == 0

    @pytest.mark.anyio
    async def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Network error")

        def success_func():
            return "success"

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)
        assert cb.failure_count == 2

        cb.call(success_func)
        assert cb.failure_count == 0
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.anyio
    async def test_reset(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Network error")

        for _ in range(3):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.is_open

        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert not cb.is_open

    @pytest.mark.anyio
    async def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=0)

        def failing_func():
            raise httpx.RequestError("Network error")

        def success_func():
            return "success"

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.is_open

        await asyncio.sleep(0.1)

        result = cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.anyio
    async def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=0)

        def failing_func():
            raise httpx.RequestError("Network error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.is_open

        await asyncio.sleep(0.1)

        with pytest.raises(httpx.RequestError):
            cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open

    @pytest.mark.anyio
    async def test_async_call_success(self):
        import asyncio

        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        async def success_func():
            await asyncio.sleep(0)
            return "async_success"

        result = await cb.call_async(success_func)
        assert result == "async_success"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.anyio
    async def test_async_call_failure(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60)

        async def failing_func():
            raise httpx.RequestError("Async network error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                await cb.call_async(failing_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb.is_open

    @pytest.mark.anyio
    async def test_async_fails_fast_when_open(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60)

        async def failing_func():
            raise httpx.RequestError("Network error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                await cb.call_async(failing_func)

        assert cb.is_open

        async def should_not_be_called():
            raise RuntimeError("Should not execute")

        with pytest.raises(Exception) as exc_info:
            await cb.call_async(should_not_be_called)

        assert "Circuit breaker is OPEN" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_should_attempt_reset_with_no_last_failure_time(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)
        assert cb._should_attempt_reset() is True  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_should_attempt_reset_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=0)

        def failing_func():
            raise httpx.RequestError("Error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        await asyncio.sleep(0.1)
        assert cb._should_attempt_reset() is True  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_should_attempt_reset_before_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN
        assert cb._should_attempt_reset() is False  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_record_success_in_half_open_state(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=0)

        def failing_func():
            raise httpx.RequestError("Error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                cb.call(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        await asyncio.sleep(0.1)

        def success_func():
            return "success"

        result = cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.anyio
    async def test_record_failure_threshold_logging(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def failing_func():
            raise httpx.RequestError("Error")

        with pytest.raises(httpx.RequestError):
            cb.call(failing_func)
        assert cb.failure_count == 1
        assert cb.state == CircuitBreakerState.CLOSED

        with pytest.raises(httpx.RequestError):
            cb.call(failing_func)
        assert cb.failure_count == 2

        with pytest.raises(httpx.RequestError):
            cb.call(failing_func)
        assert cb.state == CircuitBreakerState.OPEN
        assert cb._last_state_change is not None  # type: ignore[attr-defined]

    @pytest.mark.anyio
    async def test_async_state_transition_open_to_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=0)

        async def failing_func():
            raise httpx.RequestError("Error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                await cb.call_async(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        await asyncio.sleep(0.1)

        async def success_func():
            return "success"

        result = await cb.call_async(success_func)
        assert result == "success"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.anyio
    async def test_async_fail_fast_when_open(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=60)

        async def failing_func():
            raise httpx.RequestError("Error")

        for _ in range(2):
            with pytest.raises(httpx.RequestError):
                await cb.call_async(failing_func)

        assert cb.state == CircuitBreakerState.OPEN

        call_count = [0]

        async def should_not_be_called():
            call_count[0] += 1
            return "should not execute"

        with pytest.raises(RuntimeError) as exc_info:
            await cb.call_async(should_not_be_called)

        assert "Circuit breaker is OPEN" in str(exc_info.value)
        assert call_count[0] == 0

    @pytest.mark.anyio
    async def test_async_callable_with_args(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        async def func_with_args(arg1: str, arg2: str, kwarg: str | None = None) -> str:
            return f"{arg1}-{arg2}-{kwarg}"

        result = await cb.call_async(func_with_args, "a", "b", kwarg="c")
        assert result == "a-b-c"

    @pytest.mark.anyio
    async def test_async_not_awaitable_error(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        def not_async_func():
            return "not awaitable"

        with pytest.raises(TypeError) as exc_info:
            await cb.call_async(not_async_func)

        assert "expects an awaitable" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_async_with_args_not_callable_error(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)

        async def some_coro():
            return "result"

        coro = some_coro()
        with pytest.raises(TypeError) as exc_info:
            await cb.call_async(coro, "extra_arg")

        assert "received positional/keyword args but the first argument is not callable" in str(
            exc_info.value
        )

        # Await the coroutine to avoid the warning
        await coro
