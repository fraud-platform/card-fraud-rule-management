"""
OpenTelemetry distributed tracing configuration for Fraud Governance API.

This module provides automatic instrumentation for:
- FastAPI (HTTP requests/responses)
- SQLAlchemy (database queries)
- HTTPX (outbound HTTP calls)

Configuration via environment variables:
- OTEL_ENABLED: Enable/disable tracing (default: true)
- OTEL_SERVICE_NAME: Service name for traces (default: fraud-governance-api)
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (default: http://localhost:4317)
- OTEL_EXPORTER_OTLP_HEADERS: Optional headers for OTLP exporter
- OTEL_TRACES_SAMPLER: Sampling strategy (default: parent_trace_always)
- OTEL_TRACES_SAMPLER_ARG: Sampling rate (default: 1.0)

Usage:
    from app.core.telemetry import init_telemetry, shutdown_telemetry

    # On application startup
    init_telemetry()

    # On application shutdown
    shutdown_telemetry()
"""

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

logger = logging.getLogger(__name__)

# Global tracer provider reference for shutdown
_tracer_provider: TracerProvider | None = None


def _parse_headers(headers_string: str | None) -> dict[str, str]:
    """
    Parse OTLP headers from environment variable format.

    Args:
        headers_string: Headers in format "key1=value1,key2=value2"

    Returns:
        Dictionary of headers
    """
    if not headers_string:
        return {}

    headers = {}
    for pair in headers_string.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def _create_resource(
    service_name: str,
    app_env: str,
    app_region: str,
    app_version: str = "0.1.0",
) -> Resource:
    """
    Create OpenTelemetry resource with service metadata.

    Args:
        service_name: Name of the service
        app_env: Deployment environment (local/test/prod)
        app_region: Geographic region
        app_version: Service version

    Returns:
        OpenTelemetry Resource object
    """
    attributes = {
        SERVICE_NAME: service_name,
        DEPLOYMENT_ENVIRONMENT: app_env,
        "app.region": app_region,
        "service.version": app_version,
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.auto_instrumented": "false",
    }

    return Resource.create(attributes)


def init_telemetry(
    service_name: str | None = None,
    app_env: str | None = None,
    app_region: str | None = None,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    sampler_name: str | None = None,
    sampler_arg: float | None = None,
    sqlalchemy_engine: Any = None,
) -> TracerProvider | None:
    """
    Initialize OpenTelemetry distributed tracing.

    Sets up:
    - Tracer provider with resource attributes
    - OTLP span exporter (with configurable endpoint and headers)
    - Batch span processor for efficient export
    - FastAPI instrumentation
    - SQLAlchemy instrumentation (if engine provided)
    - HTTPX instrumentation

    Args:
        service_name: Service name (defaults to OTEL_SERVICE_NAME env var)
        app_env: Environment (local/test/prod)
        app_region: Geographic region
        otlp_endpoint: OTLP collector endpoint (defaults to OTEL_EXPORTER_OTLP_ENDPOINT)
        otlp_headers: OTLP exporter headers (defaults to OTEL_EXPORTER_OTLP_HEADERS)
        sampler_name: Sampling strategy (defaults to OTEL_TRACES_SAMPLER)
        sampler_arg: Sampling rate (defaults to OTEL_TRACES_SAMPLER_ARG)
        sqlalchemy_engine: SQLAlchemy engine to instrument

    Returns:
        TracerProvider instance if enabled, None otherwise

    Example:
        from app.core.config import settings
        from app.db.session import engine

        init_telemetry(
            service_name=settings.otel_service_name,
            app_env=settings.app_env,
            app_region=settings.app_region,
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            otlp_headers=settings.otel_exporter_otlp_headers,
            sampler_name=settings.otel_traces_sampler,
            sampler_arg=settings.otel_traces_sampler_arg,
            sqlalchemy_engine=engine,
        )
    """
    global _tracer_provider

    # Import settings for defaults
    from app.core.config import settings

    # Use provided values or fall back to settings
    service_name = service_name or settings.otel_service_name
    app_env = app_env or settings.app_env
    app_region = app_region or settings.app_region
    otlp_endpoint = otlp_endpoint or settings.otel_exporter_otlp_endpoint
    otlp_headers = otlp_headers or settings.otel_exporter_otlp_headers
    sampler_name = sampler_name or settings.otel_traces_sampler
    sampler_arg = sampler_arg if sampler_arg is not None else settings.otel_traces_sampler_arg

    # Check if OpenTelemetry is enabled
    if not settings.otel_enabled:
        logger.info("OpenTelemetry tracing is disabled (OTEL_ENABLED=false)")
        return None

    try:
        # Create resource with service metadata
        resource = _create_resource(
            service_name=service_name,
            app_env=app_env,
            app_region=app_region,
        )

        # Configure sampler
        # Support common sampling strategies: parent_trace_always, always_on, always_off, traceidratio
        if sampler_name == "always_on":
            from opentelemetry.sdk.trace.sampling import ALWAYS_ON

            sampler = ALWAYS_ON
        elif sampler_name == "always_off":
            from opentelemetry.sdk.trace.sampling import ALWAYS_OFF

            sampler = ALWAYS_OFF
        elif sampler_name == "traceidratio":
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

            sampler = TraceIdRatioBased(sampler_arg)
        else:  # parent_trace_always (default)
            from opentelemetry.sdk.trace.sampling import (
                ParentBased,
                TraceIdRatioBased,
            )

            # ParentBased requires a Sampler object for the root parameter
            # The root sampler should be a TraceIdRatioBased with the ratio
            root_sampler = TraceIdRatioBased(sampler_arg)
            sampler = ParentBased(root=root_sampler)

        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource, sampler=sampler)
        _tracer_provider = tracer_provider

        # Configure OTLP exporter
        headers = _parse_headers(otlp_headers)

        # Use gRPC OTLP exporter (port 4317)
        # For HTTP/JSON, use port 4318 and OTLPSpanExporter with protocol="http/protobuf"
        span_exporter: SpanExporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            headers=headers,
        )

        # Add batch span processor for efficient export
        batch_processor = BatchSpanProcessor(span_exporter)
        tracer_provider.add_span_processor(batch_processor)

        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)

        logger.info(
            f"OpenTelemetry initialized: service={service_name}, "
            f"environment={app_env}, region={app_region}, "
            f"endpoint={otlp_endpoint}, sampler={sampler_name}"
        )

        return tracer_provider

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}", exc_info=True)
        return None


def instrument_fastapi(app: Any) -> None:
    """
    Instrument FastAPI application with OpenTelemetry.

    Args:
        app: FastAPI application instance
    """
    from app.core.config import settings

    if not settings.otel_enabled:
        logger.debug("OpenTelemetry disabled - skipping FastAPI instrumentation")
        return

    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI: {e}", exc_info=True)


def instrument_sqlalchemy(engine: Any) -> None:
    """
    Instrument SQLAlchemy engine with OpenTelemetry.

    Args:
        engine: SQLAlchemy engine instance
    """
    from app.core.config import settings

    if not settings.otel_enabled:
        logger.debug("OpenTelemetry disabled - skipping SQLAlchemy instrumentation")
        return

    try:
        SQLAlchemyInstrumentor().instrument(
            engine=engine,
            enable_commenter=True,  # Add SQL comments with trace info
        )
        logger.info("SQLAlchemy instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument SQLAlchemy: {e}", exc_info=True)


def instrument_httpx() -> None:
    """
    Instrument HTTPX client with OpenTelemetry.

    Automatically instruments all HTTPX client instances for
    outbound HTTP request tracing.
    """
    from app.core.config import settings

    if not settings.otel_enabled:
        logger.debug("OpenTelemetry disabled - skipping HTTPX instrumentation")
        return

    try:
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument HTTPX: {e}", exc_info=True)


def shutdown_telemetry() -> None:
    """
    Shutdown OpenTelemetry tracer provider gracefully.

    Flushes all pending spans and closes connections to OTLP collector.
    Should be called on application shutdown.

    Example:
        @app.on_event("shutdown")
        async def shutdown_event():
            shutdown_telemetry()
    """
    global _tracer_provider

    if _tracer_provider is None:
        logger.debug("OpenTelemetry tracer provider not initialized")
        return

    try:
        logger.info("Shutting down OpenTelemetry tracer provider")
        _tracer_provider.shutdown()
        _tracer_provider = None
        logger.info("OpenTelemetry shutdown complete")
    except Exception as e:
        logger.error(f"Error during OpenTelemetry shutdown: {e}", exc_info=True)


def get_trace_id() -> str | None:
    """
    Get the current trace ID from OpenTelemetry context.

    Returns:
        Trace ID as hex string, or None if no active span
    """
    current_span = trace.get_current_span()
    if current_span is None:
        return None

    # Check if span is recording (has valid context)
    # NonRecordingSpan is used when no span is active
    if not current_span.is_recording():
        return None

    try:
        span_context = current_span.get_span_context()
        if span_context is None:
            return None
        return format(span_context.trace_id, "032x")
    except (AttributeError, ValueError):
        return None


def get_span_id() -> str | None:
    """
    Get the current span ID from OpenTelemetry context.

    Returns:
        Span ID as hex string, or None if no active span
    """
    current_span = trace.get_current_span()
    if current_span is None:
        return None

    # Check if span is recording (has valid context)
    if not current_span.is_recording():
        return None

    try:
        span_context = current_span.get_span_context()
        if span_context is None:
            return None
        return format(span_context.span_id, "016x")
    except (AttributeError, ValueError):
        return None
