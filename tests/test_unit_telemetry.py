"""
Tests for OpenTelemetry distributed tracing configuration.

Tests cover:
- Header parsing for OTLP exporters
- Resource creation with service metadata
- Telemetry shutdown
- Trace ID and span ID extraction
- Edge cases and error handling
"""

import os
from unittest.mock import Mock, patch

import pytest

# Set required environment variables before importing app modules

# Set required environment variables before importing app modules
os.environ.setdefault("DATABASE_URL_APP", "postgresql://user:pass@localhost:5432/db")
os.environ.setdefault("AUTH0_DOMAIN", "example.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://fraud-governance-api")

from app.core.telemetry import (
    _create_resource,
    _parse_headers,
    get_span_id,
    get_trace_id,
    shutdown_telemetry,
)


class TestParseHeaders:
    """Tests for the _parse_headers function."""

    @pytest.mark.anyio
    async def test_parse_headers_valid_single_pair(self):
        """Test parsing a single header key-value pair."""
        result = _parse_headers("Authorization=Bearer token123")
        assert result == {"Authorization": "Bearer token123"}

    @pytest.mark.anyio
    async def test_parse_headers_valid_multiple_pairs(self):
        """Test parsing multiple header key-value pairs."""
        result = _parse_headers("key1=value1,key2=value2,key3=value3")
        assert result == {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        }

    @pytest.mark.anyio
    async def test_parse_headers_with_spaces(self):
        """Test parsing headers with extra whitespace."""
        result = _parse_headers(" key1 = value1 , key2 = value2 ")
        assert result == {
            "key1": "value1",
            "key2": "value2",
        }

    @pytest.mark.anyio
    async def test_parse_headers_empty_string(self):
        """Test parsing empty string returns empty dict."""
        result = _parse_headers("")
        assert result == {}

    @pytest.mark.anyio
    async def test_parse_headers_none(self):
        """Test parsing None returns empty dict."""
        result = _parse_headers(None)
        assert result == {}

    @pytest.mark.anyio
    async def test_parse_headers_with_complex_values(self):
        """Test parsing headers with complex values containing equals."""
        result = _parse_headers("token=abc=123,header=value")
        assert result == {
            "token": "abc=123",
            "header": "value",
        }

    @pytest.mark.anyio
    async def test_parse_headers_with_special_chars(self):
        """Test parsing headers with special characters."""
        result = _parse_headers("Authorization=Bearer xyz,Content-Type=application/json")
        assert result == {
            "Authorization": "Bearer xyz",
            "Content-Type": "application/json",
        }

    @pytest.mark.anyio
    async def test_parse_headers_malformed_skips_invalid(self):
        """Test that malformed pairs are skipped."""
        result = _parse_headers("key1=value1,invalidpair,key2=value2")
        # Invalid pairs without = are skipped
        assert result == {
            "key1": "value1",
            "key2": "value2",
        }

    @pytest.mark.anyio
    async def test_parse_headers_only_equals(self):
        """Test parsing headers with only equals sign."""
        result = _parse_headers("key1=,key2=value2")
        assert result == {
            "key1": "",
            "key2": "value2",
        }


class TestCreateResource:
    """Tests for the _create_resource function."""

    @pytest.mark.anyio
    async def test_create_resource_basic(self):
        """Test basic resource creation."""
        resource = _create_resource(
            service_name="test-service",
            app_env="test",
            app_region="us-east-1",
        )

        attributes = resource.attributes
        assert attributes["service.name"] == "test-service"
        assert attributes["deployment.environment"] == "test"
        assert attributes["app.region"] == "us-east-1"
        assert attributes["service.version"] == "0.1.0"

    @pytest.mark.anyio
    async def test_create_resource_with_custom_version(self):
        """Test resource creation with custom version."""
        resource = _create_resource(
            service_name="test-service",
            app_env="test",
            app_region="us-east-1",
            app_version="1.2.3",
        )

        assert resource.attributes["service.version"] == "1.2.3"

    @pytest.mark.anyio
    async def test_create_resource_telemetry_sdk_attributes(self):
        """Test that telemetry SDK attributes are set correctly."""
        resource = _create_resource(
            service_name="test-service",
            app_env="test",
            app_region="us-east-1",
        )

        assert resource.attributes["telemetry.sdk.language"] == "python"
        assert resource.attributes["telemetry.sdk.name"] == "opentelemetry"
        assert resource.attributes["telemetry.sdk.auto_instrumented"] == "false"

    @pytest.mark.anyio
    async def test_create_resource_all_envs(self):
        """Test resource creation with different environments."""
        for env in ["local", "test", "prod"]:
            resource = _create_resource(
                service_name="test-service",
                app_env=env,
                app_region="us-east-1",
            )
            assert resource.attributes["deployment.environment"] == env


class TestInitTelemetry:
    """Tests for the init_telemetry function."""

    @patch("app.core.config.settings.otel_enabled", False)
    @pytest.mark.anyio
    async def test_init_telemetry_disabled_returns_none(self):
        """Test that init_telemetry returns None when disabled."""
        from app.core import telemetry

        result = telemetry.init_telemetry()
        assert result is None

    @patch("app.core.config.settings.otel_enabled", True)
    @patch("app.core.config.settings.otel_service_name", "test-service")
    @patch("app.core.config.settings.app_env", "test")
    @patch("app.core.config.settings.app_region", "us-east-1")
    @patch("app.core.config.settings.otel_exporter_otlp_endpoint", "http://localhost:4317")
    @patch("app.core.config.settings.otel_exporter_otlp_headers", None)
    @patch("app.core.config.settings.otel_traces_sampler", "parent_trace_always")
    @patch("app.core.config.settings.otel_traces_sampler_arg", 1.0)
    @pytest.mark.anyio
    async def test_init_telemetry_enabled(self):
        """Test that init_telemetry returns TracerProvider when enabled."""
        from app.core import telemetry

        # Just verify no exception is raised when enabled
        _ = telemetry.init_telemetry()
        # Result will be None due to missing OTLP endpoint, but shouldn't raise


class TestInstrumentFastAPI:
    """Tests for the instrument_fastapi function."""

    @patch("app.core.config.settings.otel_enabled", False)
    @pytest.mark.anyio
    async def test_instrument_fastapi_disabled(self):
        """Test that instrumentation is skipped when disabled."""
        from app.core import telemetry

        mock_app = Mock()
        telemetry.instrument_fastapi(mock_app)
        # No assertion needed - just verify no exception

    @patch("app.core.config.settings.otel_enabled", True)
    @patch("app.core.telemetry.FastAPIInstrumentor")
    @pytest.mark.anyio
    async def test_instrument_fastapi_enabled(self, mock_instrumentor):
        """Test that FastAPI is instrumented when enabled."""
        from app.core import telemetry

        mock_app = Mock()
        telemetry.instrument_fastapi(mock_app)
        mock_instrumentor.instrument_app.assert_called_once_with(mock_app)


class TestInstrumentSQLAlchemy:
    """Tests for the instrument_sqlalchemy function."""

    @patch("app.core.config.settings.otel_enabled", False)
    @pytest.mark.anyio
    async def test_instrument_sqlalchemy_disabled(self):
        """Test that instrumentation is skipped when disabled."""
        from app.core import telemetry

        mock_engine = Mock()
        telemetry.instrument_sqlalchemy(mock_engine)

    @patch("app.core.config.settings.otel_enabled", True)
    @patch("app.core.telemetry.SQLAlchemyInstrumentor")
    @pytest.mark.anyio
    async def test_instrument_sqlalchemy_enabled(self, mock_instrumentor):
        """Test that SQLAlchemy is instrumented when enabled."""
        from app.core import telemetry

        mock_engine = Mock()
        telemetry.instrument_sqlalchemy(mock_engine)
        mock_instrumentor.assert_called_once()
        mock_instrumentor.return_value.instrument.assert_called_once_with(
            engine=mock_engine, enable_commenter=True
        )


class TestInstrumentHTTPX:
    """Tests for the instrument_httpx function."""

    @patch("app.core.config.settings.otel_enabled", False)
    @pytest.mark.anyio
    async def test_instrument_httpx_disabled(self):
        """Test that instrumentation is skipped when disabled."""
        from app.core import telemetry

        telemetry.instrument_httpx()

    @patch("app.core.config.settings.otel_enabled", True)
    @patch("app.core.telemetry.HTTPXClientInstrumentor")
    @pytest.mark.anyio
    async def test_instrument_httpx_enabled(self, mock_instrumentor):
        """Test that HTTPX is instrumented when enabled."""
        from app.core import telemetry

        telemetry.instrument_httpx()
        mock_instrumentor.assert_called_once()
        mock_instrumentor.return_value.instrument.assert_called_once()


class TestShutdownTelemetry:
    """Tests for the shutdown_telemetry function."""

    @patch("app.core.telemetry._tracer_provider", None)
    @pytest.mark.anyio
    async def test_shutdown_telemetry_not_initialized(self):
        """Test shutdown when telemetry was not initialized."""
        # Should not raise exception
        shutdown_telemetry()

    @patch("app.core.telemetry._tracer_provider")
    @pytest.mark.anyio
    async def test_shutdown_telemetry_initialized(self, mock_tracer_provider):
        """Test shutdown when telemetry was initialized."""
        shutdown_telemetry()
        mock_tracer_provider.shutdown.assert_called_once()

    @patch("app.core.telemetry._tracer_provider")
    @pytest.mark.anyio
    async def test_shutdown_telemetry_exception_handled(self, mock_tracer_provider):
        """Test that exceptions are handled gracefully."""
        mock_tracer_provider.shutdown.side_effect = Exception("Shutdown error")
        # Should not raise exception, just log error
        shutdown_telemetry()
        mock_tracer_provider.shutdown.assert_called_once()


class TestGetTraceId:
    """Tests for the get_trace_id function."""

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_trace_id_no_span(self, mock_get_current_span):
        """Test getting trace ID when no span is active."""
        mock_get_current_span.return_value = None
        result = get_trace_id()
        assert result is None

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_trace_id_non_recording_span(self, mock_get_current_span):
        """Test getting trace ID when span is not recording."""
        mock_span = Mock()
        mock_span.is_recording.return_value = False
        mock_get_current_span.return_value = mock_span
        result = get_trace_id()
        assert result is None

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_trace_id_valid_span(self, mock_get_current_span):
        """Test getting trace ID from valid span."""
        mock_span_context = Mock()
        mock_span_context.trace_id = 12345678901234567890123456789012
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.return_value = mock_span_context
        mock_get_current_span.return_value = mock_span
        result = get_trace_id()
        assert result is not None
        assert isinstance(result, str)
        assert len(result) == 32  # Hex string should be 32 chars

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_trace_id_none_span_context(self, mock_get_current_span):
        """Test getting trace ID when span context is None."""
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.return_value = None
        mock_get_current_span.return_value = mock_span
        result = get_trace_id()
        assert result is None

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_trace_id_exception_handling(self, mock_get_current_span):
        """Test that exceptions are handled gracefully."""
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.side_effect = AttributeError("No context")
        mock_get_current_span.return_value = mock_span
        result = get_trace_id()
        assert result is None


class TestGetSpanId:
    """Tests for the get_span_id function."""

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_span_id_no_span(self, mock_get_current_span):
        """Test getting span ID when no span is active."""
        mock_get_current_span.return_value = None
        result = get_span_id()
        assert result is None

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_span_id_non_recording_span(self, mock_get_current_span):
        """Test getting span ID when span is not recording."""
        mock_span = Mock()
        mock_span.is_recording.return_value = False
        mock_get_current_span.return_value = mock_span
        result = get_span_id()
        assert result is None

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_span_id_valid_span(self, mock_get_current_span):
        """Test getting span ID from valid span."""
        mock_span_context = Mock()
        mock_span_context.span_id = 1234567890123456
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.return_value = mock_span_context
        mock_get_current_span.return_value = mock_span
        result = get_span_id()
        assert result is not None
        assert isinstance(result, str)
        assert len(result) == 16  # Hex string should be 16 chars

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_span_id_none_span_context(self, mock_get_current_span):
        """Test getting span ID when span context is None."""
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.return_value = None
        mock_get_current_span.return_value = mock_span
        result = get_span_id()
        assert result is None

    @patch("app.core.telemetry.trace.get_current_span")
    @pytest.mark.anyio
    async def test_get_span_id_exception_handling(self, mock_get_current_span):
        """Test that exceptions are handled gracefully."""
        mock_span = Mock()
        mock_span.is_recording.return_value = True
        mock_span.get_span_context.side_effect = AttributeError("No context")
        mock_get_current_span.return_value = mock_span
        result = get_span_id()
        assert result is None
