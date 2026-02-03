"""
Circuit breaker pattern for handling external service failures gracefully.

The circuit breaker prevents cascading failures by:
1. Tracking consecutive failures
2. Opening the circuit after threshold is reached
3. Keeping circuit open for timeout period
4. Allowing half-open state to test recovery
5. Falling back to cached data when open

State transitions:
    CLOSED → OPEN (after failure_threshold consecutive failures)
    OPEN → HALF_OPEN (after timeout_seconds)
    HALF_OPEN → CLOSED (on successful fetch)
    HALF_OPEN → OPEN (on failed fetch)
    CLOSED → CLOSED (on successful fetch, resets failure count)
"""

import asyncio
import logging
import threading
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(RuntimeError):
    """Raised when circuit breaker is open and requests fail fast."""

    pass


class CircuitBreaker:
    """
    Circuit breaker for handling service failures gracefully.

    Attributes:
        failure_threshold: Number of consecutive failures before opening
        timeout_seconds: Seconds to wait before transitioning from OPEN to HALF_OPEN
        expected_exception counts as a failure: Exception type that
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        expected_exception: type[Exception] = Exception,
    ):
        self._failure_threshold = failure_threshold
        self._timeout_seconds = timeout_seconds
        self._expected_exception = expected_exception

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._last_state_change: datetime | None = None

        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()

    def _should_attempt_reset(self) -> bool:
        if self._last_failure_time is None:
            return True

        elapsed = (datetime.now(UTC) - self._last_failure_time).total_seconds()
        return elapsed >= self._timeout_seconds

    def _record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = datetime.now(UTC)

        if self._failure_count >= self._failure_threshold:
            self._state = CircuitBreakerState.OPEN
            self._last_state_change = datetime.now(UTC)
            logger.error(
                f"Circuit breaker OPEN after {self._failure_count} consecutive failures. "
                f"Will allow retry after {self._timeout_seconds} seconds."
            )
        else:
            logger.warning(
                f"Circuit breaker failure count: {self._failure_count}/{self._failure_threshold}"
            )

    def _record_success(self) -> None:
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            self._last_state_change = datetime.now(UTC)
            logger.info("Circuit breaker CLOSED - service has recovered")
        elif self._state == CircuitBreakerState.CLOSED:
            self._failure_count = 0

    def call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Execute a function through the circuit breaker (sync version).

        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of func

        Raises:
            Exception: If circuit is open or func raises expected exception
        """
        with self._lock:
            if self._state == CircuitBreakerState.OPEN and self._should_attempt_reset():
                self._state = CircuitBreakerState.HALF_OPEN
                self._last_state_change = datetime.now(UTC)
                logger.info("Circuit breaker HALF_OPEN - attempting recovery")

            if self._state == CircuitBreakerState.OPEN:
                logger.warning(
                    f"Circuit breaker is OPEN - failing fast. "
                    f"Retry after {self._timeout_seconds - (datetime.now(UTC) - self._last_failure_time).total_seconds():.1f} seconds"
                )
                raise CircuitBreakerOpenError("Circuit breaker is OPEN - service unavailable")

        try:
            result = func(*args, **kwargs)
            with self._lock:
                self._record_success()
            return result
        except self._expected_exception:
            with self._lock:
                self._record_failure()
            raise

    async def call_async(self, coro_or_func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Execute a coroutine through the circuit breaker (async version).

        Args:
            coro_or_func: Coroutine/awaitable OR a callable returning an awaitable
            *args: Positional arguments if passing a callable
            **kwargs: Keyword arguments if passing a callable

        Returns:
            Result of coroutine

        Raises:
            Exception: If circuit is open or coro raises expected exception
        """
        import inspect

        async with self._async_lock:
            if self._state == CircuitBreakerState.OPEN and self._should_attempt_reset():
                self._state = CircuitBreakerState.HALF_OPEN
                self._last_state_change = datetime.now(UTC)
                logger.info("Circuit breaker HALF_OPEN - attempting recovery")

            if self._state == CircuitBreakerState.OPEN:
                logger.warning(
                    f"Circuit breaker is OPEN - failing fast. "
                    f"Retry after {self._timeout_seconds - (datetime.now(UTC) - self._last_failure_time).total_seconds():.1f} seconds"
                )
                raise CircuitBreakerOpenError("Circuit breaker is OPEN - service unavailable")

        if callable(coro_or_func):
            awaitable = coro_or_func(*args, **kwargs)
        else:
            if args or kwargs:
                raise TypeError(
                    "call_async() received positional/keyword args but the first argument is not callable"
                )
            awaitable = coro_or_func

        if not inspect.isawaitable(awaitable):
            raise TypeError(
                "call_async() expects an awaitable or a callable returning an awaitable"
            )

        try:
            result = await awaitable
            async with self._async_lock:
                self._record_success()
            return result
        except self._expected_exception:
            async with self._async_lock:
                self._record_failure()
            raise

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    @property
    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self._state == CircuitBreakerState.OPEN

    def reset(self) -> None:
        """Reset the circuit breaker to CLOSED state (useful for testing)."""
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            self._last_state_change = None
            logger.debug("Circuit breaker reset to CLOSED state")
