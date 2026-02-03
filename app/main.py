import hmac
import logging
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import test_utils
from app.api.routes.approvals import router as approvals_router
from app.api.routes.field_registry import router as field_registry_router
from app.api.routes.health import router as health_router
from app.api.routes.rule_fields import router as rule_fields_router
from app.api.routes.rules import router as rules_router
from app.api.routes.rulesets import router as rulesets_router
from app.core.config import settings
from app.core.errors import (
    FraudGovError,
    get_status_code,
)
from app.core.middleware import RequestSizeLimitMiddleware
from app.core.observability import (
    ObservabilityMiddleware,
    configure_structured_logging,
    extract_request_context,
    metrics_endpoint,
)
from app.core.rate_limit import RateLimitMiddleware
from app.core.request_logging import RequestLoggingMiddleware
from app.core.security_middleware import SecurityHeadersMiddleware
from app.core.telemetry import (
    init_telemetry,
    instrument_fastapi,
    instrument_httpx,
    shutdown_telemetry,
)

# Configure structured logging before creating logger
if settings.observability_structured_logs:
    configure_structured_logging(settings.app_log_level)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _sanitize_error_details(details: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize error details to prevent information leakage in production.

    Removes sensitive information like:
    - File paths
    - SQL queries
    - Internal stack traces
    - Database schema details

    Args:
        details: Original error details dictionary

    Returns:
        Sanitized details dictionary
    """
    if settings.app_env != "prod":
        # In non-production, return all details for debugging
        return details

    sanitized = {}
    sensitive_patterns = [
        r"[/\\][\w/-]+\.py",  # File paths
        r"SELECT.*FROM.*WHERE",  # SQL queries (case insensitive)
        r"INSERT INTO.*VALUES",  # SQL queries
        r"UPDATE.*SET.*WHERE",  # SQL queries
        r"DELETE FROM.*WHERE",  # SQL queries
        r"schema\s*[:=]\s*\w+",  # Schema references
        r"table\s*[:=]\s*\w+",  # Table references
    ]

    for key, value in details.items():
        if isinstance(value, str):
            # Check for sensitive patterns
            for pattern in sensitive_patterns:
                if re.search(pattern, value, re.IGNORECASE):
                    sanitized[key] = "[REDACTED]"
                    break
            else:
                sanitized[key] = value
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_error_details(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_error_details(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            sanitized[key] = value

    return sanitized


def _log_security_event(
    request: Request,
    event_type: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Log security-related events for audit trail.

    Args:
        request: The incoming request
        event_type: Type of security event (e.g., "AUTH_FAILURE", "AUTHZ_FAILURE")
        status_code: HTTP status code
        details: Additional event details
    """
    # Build security event log with context
    security_event = {
        "event_type": event_type,
        "client_ip": request.client.host if request.client else "unknown",
        "path": request.url.path,
        "method": request.method,
        "status_code": status_code,
        "user_agent": request.headers.get("user-agent", "unknown"),
        "details": details or {},
        **extract_request_context(request),
    }

    # Log with structured format
    logger.warning(
        f"Security event: {event_type}",
        extra={
            "security_event": True,
            **security_event,
        },
    )


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Sets up:
    - OpenTelemetry distributed tracing
    - Structured logging with correlation IDs
    - CORS middleware
    - Observability middleware (metrics, request tracking)
    - Security middleware (rate limiting, request size limits)
    - Exception handlers for domain errors
    - API routers
    - Metrics endpoint for Prometheus scraping
    """
    app = FastAPI(
        title="Fraud Governance API",
        description="Fraud rule governance and compilation control-plane",
        version="0.1.0",
    )

    # ============================================================================
    # OpenTelemetry Distributed Tracing
    # ============================================================================

    # Initialize telemetry on startup
    @app.on_event("startup")
    async def startup_telemetry():
        """Initialize OpenTelemetry tracing and instrumentation."""
        # Initialize tracer provider
        init_telemetry(
            service_name=settings.otel_service_name,
            app_env=settings.app_env,
            app_region=settings.app_region,
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            otlp_headers=settings.otel_exporter_otlp_headers,
            sampler_name=settings.otel_traces_sampler,
            sampler_arg=settings.otel_traces_sampler_arg,
        )

        # Instrument FastAPI after app creation
        instrument_fastapi(app)

        # Instrument HTTPX for outbound HTTP calls
        instrument_httpx()

        # Note: SQLAlchemy instrumentation happens in app/db/session.py
        # after engine is created

    # Shutdown telemetry on shutdown
    @app.on_event("shutdown")
    async def shutdown_app():
        """Shutdown OpenTelemetry tracer provider gracefully."""
        shutdown_telemetry()

    # ============================================================================
    # Observability Middleware (must be first for correlation tracking)
    # ============================================================================

    if settings.observability_enabled:
        app.add_middleware(ObservabilityMiddleware)

    # ============================================================================
    # Security Headers Middleware (must be before CORS)
    # ============================================================================

    app.add_middleware(SecurityHeadersMiddleware)

    # ============================================================================
    # Request/Response Logging Middleware
    # ============================================================================

    # Enable in local/test, or via API_REQUEST_LOGGING=true
    if settings.app_env in ("local", "test"):
        app.add_middleware(RequestLoggingMiddleware)

    # ============================================================================
    # CORS Configuration
    # ============================================================================

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],  # Allow all HTTP methods
        allow_headers=["*"],  # Allow all headers including Authorization
    )

    # ============================================================================
    # Security Middleware
    # ============================================================================

    # Add request size limit middleware (prevents DoS from large payloads)
    app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

    # Add rate limiting middleware (prevents abuse)
    app.add_middleware(RateLimitMiddleware)

    # ============================================================================
    # Exception Handlers
    # ============================================================================

    @app.exception_handler(FraudGovError)
    async def fraud_gov_error_handler(request: Request, exc: FraudGovError) -> JSONResponse:
        """
        Handle domain-specific errors from the fraud governance system.

        Maps domain exceptions to appropriate HTTP status codes and
        returns structured error responses.

        Args:
            request: The incoming request
            exc: The domain exception raised

        Returns:
            JSON response with error details
        """
        status_code = get_status_code(exc)

        # Include request context in logs
        context = {
            "details": exc.details,
            "path": request.url.path,
            **extract_request_context(request),
        }

        # Log errors with appropriate severity
        if status_code >= 500:
            logger.error(
                f"{exc.__class__.__name__}: {exc.message}",
                extra=context,
            )
        elif status_code >= 400:
            logger.warning(
                f"{exc.__class__.__name__}: {exc.message}",
                extra=context,
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "error": exc.__class__.__name__,
                "message": exc.message,
                "details": _sanitize_error_details(exc.details),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """
        Handle FastAPI HTTP exceptions (including auth errors).

        Provides consistent error response format for all HTTP exceptions,
        including those raised by authentication/authorization middleware.

        Args:
            request: The incoming request
            exc: The HTTP exception raised

        Returns:
            JSON response with error details
        """
        # Include request context in security events
        context = {
            "path": request.url.path,
            "method": request.method,
            **extract_request_context(request),
        }

        # Log security events for auth/authorization failures
        if exc.status_code == 401:
            _log_security_event(
                request,
                event_type="AUTH_FAILURE",
                status_code=401,
                details={"reason": str(exc.detail)},
            )
        elif exc.status_code == 403:
            _log_security_event(
                request,
                event_type="AUTHZ_FAILURE",
                status_code=403,
                details={"reason": str(exc.detail)},
            )
        elif exc.status_code >= 500:
            logger.error(
                f"HTTP {exc.status_code}: {exc.detail}",
                extra=context,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "HTTPException",
                "message": exc.detail,
                "details": {},
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler for unexpected exceptions.

        Logs the full exception and returns a generic 500 error to the client
        without exposing internal implementation details.

        Args:
            request: The incoming request
            exc: The unexpected exception

        Returns:
            JSON response with generic error message
        """
        context = {
            "path": request.url.path if request.url else "unknown",
            **extract_request_context(request),
        }
        logger.error(
            f"Unhandled exception: {exc}",
            exc_info=True,
            extra=context,
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred",
                "details": {},
            },
        )

    # ============================================================================
    # Router Registration
    # ============================================================================

    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(rule_fields_router, prefix=API_PREFIX)
    app.include_router(field_registry_router, prefix=API_PREFIX)
    app.include_router(rules_router, prefix=API_PREFIX)
    app.include_router(approvals_router, prefix=API_PREFIX)
    app.include_router(rulesets_router, prefix=API_PREFIX)

    # Test utilities (ONLY in local and test, NEVER in production)
    if settings.app_env in ("local", "test"):
        app.include_router(test_utils.router, prefix=API_PREFIX, tags=["test-utils"])

    # ============================================================================
    # Metrics Endpoint (Prometheus) - Token Protected
    # ============================================================================

    async def protected_metrics(request: Request) -> Response:
        """
        Protected Prometheus metrics endpoint.

        SECURITY: Always requires authentication via X-Metrics-Token header.
        Exposes internal system metrics that could aid reconnaissance if leaked.
        """
        from app.core.config import settings

        # Verify token is configured
        expected_token = settings.metrics_token
        if not expected_token:
            logger.error(
                "Metrics endpoint accessed but METRICS_TOKEN not configured",
                extra={"security_event": True, "event_type": "METRICS_NOT_CONFIGURED"},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Metrics token not configured. Set METRICS_TOKEN environment variable.",
            )

        # Verify token using constant-time comparison to prevent timing attacks
        metrics_token = request.headers.get("X-Metrics-Token")
        if not hmac.compare_digest(metrics_token or "", expected_token):
            logger.warning(
                "Unauthorized metrics access attempt",
                extra={
                    "security_event": True,
                    "event_type": "METRICS_ACCESS_DENIED",
                    "client_ip": request.client.host if request.client else "unknown",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid metrics token",
            )

        return metrics_endpoint()

    if settings.observability_enabled:
        app.add_route("/metrics", protected_metrics)

    return app


app = create_app()
