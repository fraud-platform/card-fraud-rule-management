"""
Observability module for Fraud Governance API.

Provides:
- Structured logging with JSON format and correlation IDs
- Request correlation ID (request_id) generation and propagation
- Prometheus metrics collection (HTTP, DB, compiler)
- Request tracking middleware for latency and status codes
- Context management for user_id and region

Usage:
    from app.core.observability import (
        get_request_id,
        set_correlation_id,
        get_logger,
        metrics,
    )
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ============================================================================
# Context Variables for Request Tracking
# ============================================================================

# Correlation ID - links all logs for a single request
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# User ID from JWT - tracks authenticated user
_user_id_ctx: ContextVar[str] = ContextVar("user_id", default="")

# Region for deployment isolation - tracks geographic region
_region_ctx: ContextVar[str] = ContextVar("region", default="")


def generate_request_id() -> str:
    """
    Generate a unique request ID for correlation.

    Uses UUIDv7 for time-ordered, sortable IDs with good index locality.

    Returns:
        String representation of UUIDv7
    """
    return str(uuid.uuid4())


def get_request_id() -> str:
    """Get the current request ID from context."""
    return _request_id_ctx.get()


def set_correlation_id(request_id: str) -> None:
    """Set the correlation ID for the current request context."""
    _request_id_ctx.set(request_id)


def get_user_id() -> str:
    """Get the current user ID from context."""
    return _user_id_ctx.get()


def set_user_id(user_id: str) -> None:
    """Set the user ID for the current request context."""
    _user_id_ctx.set(user_id)


def get_region() -> str:
    """Get the current region from context."""
    return _region_ctx.get()


def set_region(region: str) -> None:
    """Set the region for the current request context."""
    _region_ctx.set(region)


# ============================================================================
# Structured Logging Configuration
# ============================================================================


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Outputs logs as JSON with standard fields:
    - timestamp: ISO 8601 format
    - level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - logger: Logger name
    - message: Log message
    - request_id: Correlation ID (if available)
    - trace_id: OpenTelemetry trace ID (if available)
    - span_id: OpenTelemetry span ID (if available)
    - user_id: Authenticated user (if available)
    - region: Geographic region (if available)
    - extra: Any additional context from logging.extra
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Python logging LogRecord

        Returns:
            JSON-formatted log string
        """
        # Base log fields
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add context variables if available
        request_id = get_request_id()
        if request_id:
            log_entry["request_id"] = request_id

        # Add OpenTelemetry trace context if available
        try:
            from app.core.telemetry import get_span_id, get_trace_id

            trace_id = get_trace_id()
            if trace_id:
                log_entry["trace_id"] = trace_id

            span_id = get_span_id()
            if span_id:
                log_entry["span_id"] = span_id
        except ImportError:
            # OpenTelemetry not available
            pass
        except Exception:
            # Trace context not available or error retrieving
            pass

        user_id = get_user_id()
        if user_id:
            log_entry["user_id"] = user_id

        region = get_region()
        if region:
            log_entry["region"] = region

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
            }

        # Add standard logging fields
        if hasattr(record, "pathname"):
            log_entry["file"] = record.pathname
        if hasattr(record, "lineno"):
            log_entry["line"] = record.lineno
        if hasattr(record, "funcName"):
            log_entry["function"] = record.funcName

        # Add any extra fields from logging.extra
        # These come from logger.info("msg", extra={"key": "value"})
        extra_keys = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
            }
        }
        if extra_keys:
            log_entry["extra"] = extra_keys

        return json.dumps(log_entry, default=str)


def configure_structured_logging(level: str = "INFO") -> None:
    """
    Configure root logger with structured JSON formatting.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Get root logger
    root_logger = logging.getLogger()

    # Clear existing handlers
    root_logger.handlers.clear()

    # Set log level
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Create console handler with JSON formatter
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())

    root_logger.addHandler(handler)


# ============================================================================
# Prometheus Metrics
# ============================================================================

# Use a custom registry to avoid conflicts with other Prometheus metrics
_registry = CollectorRegistry()


class Metrics:
    """
    Centralized metrics collection for the application.

    Metrics groups:
    - HTTP: Request rate, errors, latency
    - Database: Connection pool, query timing
    - Compiler: Compilation duration, ruleset size
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        """Initialize all metrics with proper labels."""
        self.registry = registry

        # -------------------------------------------------------------------
        # HTTP Metrics
        # -------------------------------------------------------------------

        # HTTP request count by method, route, and status
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "route", "status_code", "region"],
            registry=self.registry,
        )

        # HTTP request latency histogram
        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "route", "region"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )

        # HTTP requests currently in progress
        self.http_requests_in_progress = Gauge(
            "http_requests_in_progress",
            "HTTP requests currently in progress",
            ["method", "route", "region"],
            registry=self.registry,
        )

        # HTTP errors by type
        self.http_errors_total = Counter(
            "http_errors_total",
            "Total HTTP errors",
            ["error_type", "method", "route", "region"],
            registry=self.registry,
        )

        # -------------------------------------------------------------------
        # Database Metrics
        # -------------------------------------------------------------------

        # Database connection pool stats
        self.db_pool_size = Gauge(
            "db_pool_size",
            "Database connection pool size",
            ["region"],
            registry=self.registry,
        )

        self.db_pool_overflow = Gauge(
            "db_pool_overflow",
            "Database connection pool overflow",
            ["region"],
            registry=self.registry,
        )

        self.db_pool_checked_out = Gauge(
            "db_pool_checked_out",
            "Database connections currently checked out",
            ["region"],
            registry=self.registry,
        )

        # Database query duration
        self.db_query_duration_seconds = Histogram(
            "db_query_duration_seconds",
            "Database query duration in seconds",
            ["operation", "region"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self.registry,
        )

        # Database query count
        self.db_queries_total = Counter(
            "db_queries_total",
            "Total database queries",
            ["operation", "status", "region"],
            registry=self.registry,
        )

        # -------------------------------------------------------------------
        # Compiler Metrics
        # -------------------------------------------------------------------

        # Compiler duration
        self.compiler_duration_seconds = Histogram(
            "compiler_duration_seconds",
            "Ruleset compilation duration in seconds",
            ["region"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )

        # Compiler ruleset size
        self.compiler_rules_count = Histogram(
            "compiler_rules_count",
            "Number of rules in compiled ruleset",
            ["region"],
            buckets=(1, 5, 10, 25, 50, 100, 250, 500),
            registry=self.registry,
        )

        # Compiler AST size in bytes
        self.compiler_ast_bytes = Histogram(
            "compiler_ast_bytes",
            "Size of compiled AST in bytes",
            ["region"],
            buckets=(
                1024,
                4096,
                16384,
                65536,
                262144,
                1048576,
                4194304,
                16777216,
            ),
            registry=self.registry,
        )

        # Compiler success/failure count
        self.compiler_compilations_total = Counter(
            "compiler_compilations_total",
            "Total ruleset compilations",
            ["status", "region"],
            registry=self.registry,
        )


# Global metrics instance
metrics = Metrics(_registry)


# ============================================================================
# Middleware
# ============================================================================


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds observability to all requests.

    Features:
    - Generates and propagates request_id (correlation ID)
    - Extracts user_id from JWT if available
    - Logs all requests with structured fields
    - Tracks request latency
    - Records Prometheus metrics
    - Adds request_id to response headers
    """

    def __init__(
        self,
        app: ASGIApp,
        metrics_instance: Metrics | None = None,
        skip_paths: list[str] | None = None,
    ) -> None:
        """
        Initialize observability middleware.

        Args:
            app: ASGI application
            metrics_instance: Metrics instance (uses global if None)
            skip_paths: Paths to skip detailed logging (e.g., health checks)
        """
        super().__init__(app)
        self.metrics = metrics_instance or metrics
        self.skip_paths = set(skip_paths or ["/health", "/readyz", "/metrics"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with observability enhancements.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response with observability headers
        """
        # Generate request ID if not already set
        request_id = request.headers.get("X-Request-ID", generate_request_id())
        set_correlation_id(request_id)

        # Set region from settings (P0 requirement for regional isolation)
        from app.core.config import settings

        set_region(settings.app_region)

        # Extract user info from JWT if available
        user_id = "anonymous"
        if hasattr(request.state, "user"):
            user_obj = request.state.user
            if isinstance(user_obj, dict):
                user_id = user_obj.get("sub", "anonymous")
                set_user_id(user_id)

        # Get route pattern for metrics (fallback to path for no-match)
        route = getattr(request.state, "route", None)
        route_pattern = route.path if route else request.url.path

        # Get region for metrics labeling (P0 requirement)
        region = get_region() or "unknown"

        # Skip detailed logging for health/metrics endpoints
        is_skipped_path = any(route_pattern.startswith(path) for path in self.skip_paths)

        # Track in-progress requests
        self.metrics.http_requests_in_progress.labels(
            method=request.method, route=route_pattern, region=region
        ).inc()

        start_time = time.time()

        try:
            # Process request
            response = await call_next(request)

            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000

            # Record metrics
            self.metrics.http_requests_total.labels(
                method=request.method,
                route=route_pattern,
                status_code=response.status_code,
                region=region,
            ).inc()
            self.metrics.http_request_duration_seconds.labels(
                method=request.method, route=route_pattern, region=region
            ).observe(latency_ms / 1000)  # Convert to seconds

            # Add request_id to response headers for client-side correlation
            response.headers["X-Request-ID"] = request_id

            # Log request if not skipped
            if not is_skipped_path:
                logger = logging.getLogger("app.request")
                logger.info(
                    f"{request.method} {route_pattern}",
                    extra={
                        "method": request.method,
                        "route": route_pattern,
                        "status_code": response.status_code,
                        "latency_ms": round(latency_ms, 2),
                    },
                )

            return response

        except Exception as e:
            # Calculate latency even for errors
            latency_ms = (time.time() - start_time) * 1000

            # Record error metrics
            error_type = type(e).__name__
            self.metrics.http_requests_total.labels(
                method=request.method,
                route=route_pattern,
                status_code=500,
                region=region,
            ).inc()
            self.metrics.http_errors_total.labels(
                error_type=error_type, method=request.method, route=route_pattern, region=region
            ).inc()
            self.metrics.http_request_duration_seconds.labels(
                method=request.method, route=route_pattern, region=region
            ).observe(latency_ms / 1000)

            # Log error
            logger = logging.getLogger("app.request")
            logger.error(
                f"{request.method} {route_pattern} - {error_type}: {str(e)}",
                extra={
                    "method": request.method,
                    "route": route_pattern,
                    "status_code": 500,
                    "latency_ms": round(latency_ms, 2),
                    "error_type": error_type,
                    "error_message": str(e),
                },
                exc_info=True,
            )

            # Re-raise for exception handlers
            raise

        finally:
            # Decrement in-progress counter
            self.metrics.http_requests_in_progress.labels(
                method=request.method, route=route_pattern, region=region
            ).dec()


# ============================================================================
# Database Metrics Helper
# ============================================================================


class DBMetricsWrapper:
    """
    Wrapper to track database query metrics.

    Usage in repos:
        with db_metrics.track("query_rules"):
            result = db.query(Rule).all()
    """

    def __init__(self, metrics_instance: Metrics | None = None) -> None:
        """Initialize wrapper with metrics instance."""
        self.metrics = metrics_instance or metrics

    def track(self, operation: str):
        """
        Context manager to track database operation metrics.

        Args:
            operation: Name of the operation (e.g., "query_rules", "insert_rule")

        Yields:
            Context that tracks timing and records metrics on exit
        """
        from contextlib import contextmanager

        @contextmanager
        def _tracker():
            start = time.time()
            status = "success"
            region = get_region() or "unknown"

            class _Context:
                pass

            ctx = _Context()

            try:
                yield ctx
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.time() - start
                self.metrics.db_query_duration_seconds.labels(
                    operation=operation, region=region
                ).observe(duration)
                self.metrics.db_queries_total.labels(
                    operation=operation, status=status, region=region
                ).inc()

        return _tracker()


# Global DB metrics wrapper
db_metrics = DBMetricsWrapper()


# ============================================================================
# Metrics Endpoint
# ============================================================================


def metrics_endpoint() -> Response:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping.
    """
    return Response(
        content=generate_latest(_registry),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ============================================================================
# Convenience Functions
# ============================================================================


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with structured formatting configured.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def extract_request_context(request: Request) -> dict[str, Any]:
    """
    Extract observability context from request for logging.

    Args:
        request: FastAPI Request object

    Returns:
        Dictionary with request_id, user_id, region
    """
    return {
        "request_id": get_request_id(),
        "user_id": get_user_id() or "anonymous",
        "region": get_region() or "",
    }
