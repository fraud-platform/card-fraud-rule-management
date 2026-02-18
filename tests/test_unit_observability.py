"""
Unit tests for observability features.

Tests cover:
- Structured logging with JSON format
- Request correlation ID (request_id) generation and propagation
- Context variables (user_id, region)
- Prometheus metrics collection
- Request tracking middleware
- Metrics endpoint
"""

import json
import logging
import re
from datetime import UTC

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from app.core.observability import (
    ObservabilityMiddleware,
    StructuredFormatter,
    configure_structured_logging,
    db_metrics,
    extract_request_context,
    generate_request_id,
    get_region,
    get_request_id,
    get_user_id,
    metrics,
    metrics_endpoint,
    set_correlation_id,
    set_region,
    set_user_id,
)


class TestRequestIdGeneration:
    """Tests for request ID generation and context management."""

    @pytest.mark.anyio
    async def test_generate_request_id_returns_uuid_format(self):
        """Test that generate_request_id returns a valid UUID string."""
        request_id = generate_request_id()
        assert isinstance(request_id, str)
        # UUIDv7 format: 8-4-4-4-12 hex digits
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        assert uuid_pattern.match(request_id)

    @pytest.mark.anyio
    async def test_request_id_context_isolation(self):
        """Test that request IDs are isolated between different contexts."""
        # Set different request IDs
        set_correlation_id("request-1")
        assert get_request_id() == "request-1"

        set_correlation_id("request-2")
        assert get_request_id() == "request-2"

    @pytest.mark.anyio
    async def test_user_id_context(self):
        """Test that user ID context works correctly."""
        # Initially empty
        assert get_user_id() == ""

        # Set and retrieve
        set_user_id("user-123")
        assert get_user_id() == "user-123"

        # Clear and verify
        set_user_id("")
        assert get_user_id() == ""

    @pytest.mark.anyio
    async def test_region_context(self):
        """Test that region context works correctly."""
        # Initially empty
        assert get_region() == ""

        # Set and retrieve
        set_region("us-east-1")
        assert get_region() == "us-east-1"

        # Clear and verify
        set_region("")
        assert get_region() == ""


class TestStructuredLogging:
    """Tests for structured JSON logging."""

    @pytest.mark.anyio
    async def test_structured_formatter_outputs_json(self):
        """Test that StructuredFormatter outputs valid JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        assert isinstance(formatted, str)

        # Verify valid JSON
        parsed = json.loads(formatted)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"

    @pytest.mark.anyio
    async def test_structured_formatter_includes_timestamp(self):
        """Test that structured logs include ISO timestamp."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert "timestamp" in parsed
        # ISO 8601 format in UTC (either 'Z' or '+00:00')
        assert parsed["timestamp"].endswith("Z") or parsed["timestamp"].endswith("+00:00")

    @pytest.mark.anyio
    async def test_structured_formatter_includes_context_vars(self):
        """Test that structured logs include context variables."""
        formatter = StructuredFormatter()

        # Set context variables
        set_correlation_id("req-123")
        set_user_id("user-456")
        set_region("us-east-1")

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["request_id"] == "req-123"
        assert parsed["user_id"] == "user-456"
        assert parsed["region"] == "us-east-1"

        # Clean up
        set_correlation_id("")
        set_user_id("")
        set_region("")

    @pytest.mark.anyio
    async def test_structured_formatter_includes_extra_fields(self):
        """Test that structured logs include extra fields from logging.extra."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        # Add extra fields
        record.custom_field = "custom_value"
        record.status_code = 200

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["extra"]["custom_field"] == "custom_value"
        assert parsed["extra"]["status_code"] == 200

    @pytest.mark.anyio
    async def test_configure_structured_logging(self):
        """Test that configure_structured_logging configures root logger."""
        # Get root logger before configuration
        root_logger = logging.getLogger()

        # Configure structured logging
        configure_structured_logging("DEBUG")

        # Verify handlers are set up
        assert len(root_logger.handlers) > 0
        assert root_logger.level == logging.DEBUG

        # Verify handler uses StructuredFormatter
        handler = root_logger.handlers[0]
        assert isinstance(handler.formatter, StructuredFormatter)

        # Reset for other tests
        root_logger.handlers.clear()


class TestObservabilityMiddleware:
    """Tests for ObservabilityMiddleware."""

    @pytest.mark.anyio
    async def test_middleware_generates_request_id(self):
        """Test that middleware generates and sets request ID."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/test")
        async def test_route():
            return {"request_id": get_request_id()}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        # Request ID should be set
        request_id = response.json()["request_id"]
        assert isinstance(request_id, str)
        assert len(request_id) > 0

    @pytest.mark.anyio
    async def test_middleware_propagates_request_id_from_header(self):
        """Test that middleware uses X-Request-ID header if provided."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/test")
        async def test_route():
            return {"request_id": get_request_id()}

        client = TestClient(app)
        provided_id = "custom-request-id-123"
        response = client.get("/test", headers={"X-Request-ID": provided_id})

        assert response.status_code == 200
        # Should use the provided ID
        assert response.json()["request_id"] == provided_id

    @pytest.mark.anyio
    async def test_middleware_adds_request_id_to_response(self):
        """Test that middleware adds X-Request-ID to response headers."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/test")
        async def test_route():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0

    @pytest.mark.anyio
    async def test_middleware_records_http_metrics(self):
        """Test that middleware records HTTP request metrics."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/test")
        async def test_route():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200

        # Check metrics were recorded
        # Note: metrics use a custom registry
        metrics_output = generate_latest(metrics.registry).decode("utf-8")

        # Should have http_requests_total metric with all labels including region
        # Prometheus label order is not guaranteed, so we check for presence of key parts
        assert "http_requests_total{" in metrics_output
        assert 'method="GET"' in metrics_output
        assert 'route="/test"' in metrics_output
        assert 'status_code="200"' in metrics_output
        assert "region=" in metrics_output  # Region label should be present

    @pytest.mark.anyio
    async def test_middleware_uses_route_template_for_path_params(self):
        """Test that middleware metrics use route templates for path params."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/rules/{rule_id}")
        async def get_rule(rule_id: str):
            return {"rule_id": rule_id}

        client = TestClient(app)
        response = client.get("/rules/0195f0fd-aaaa-7bbb-8ccc-0123456789ab")
        assert response.status_code == 200

        metrics_output = generate_latest(metrics.registry).decode("utf-8")
        assert 'route="/rules/{rule_id}"' in metrics_output
        assert 'route="/rules/0195f0fd-aaaa-7bbb-8ccc-0123456789ab"' not in metrics_output

    @pytest.mark.anyio
    async def test_middleware_uses_unmatched_label_for_404s(self):
        """Test that unmatched paths produce bounded route labels."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/does-not-exist/12345")
        assert response.status_code == 404

        metrics_output = generate_latest(metrics.registry).decode("utf-8")
        assert 'route="__unmatched__"' in metrics_output

    @pytest.mark.anyio
    async def test_middleware_skips_logging_for_health_endpoints(self):
        """Test that middleware skips detailed logging for health endpoints."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware, skip_paths=["/health", "/readyz"])

        @app.get("/health")
        def health():
            return {"status": "ok"}

        @app.get("/api")
        def api_route():
            return {"ok": True}

        client = TestClient(app)
        response1 = client.get("/health")
        response2 = client.get("/api")

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Health endpoint should not generate detailed request logs
        # API endpoint should generate detailed request logs
        # (This is tested via log capture in integration tests)


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    @pytest.mark.anyio
    async def test_metrics_endpoint_returns_prometheus_format(self):
        """Test that metrics endpoint returns Prometheus text format."""
        # Create a test app with metrics endpoint

        app = FastAPI()

        @app.get("/metrics")
        def metrics_route():
            return metrics_endpoint()

        client = TestClient(app)
        response = client.get("/metrics")

        assert response.status_code == 200
        # Content-type header may vary in parameter order
        assert "text/plain" in response.headers["content-type"]
        assert "charset=utf-8" in response.headers["content-type"]
        assert "version=0.0.4" in response.headers["content-type"]

        # Should contain Prometheus metrics
        body = response.text
        assert "http_requests_total" in body or "# HELP" in body

    @pytest.mark.anyio
    async def test_metrics_include_http_metrics(self):
        """Test that metrics include HTTP request metrics."""
        # Make some requests first
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/test1")
        def test1():
            return {"ok": True}

        @app.post("/test2")
        def test2():
            return {"ok": True}

        # Add metrics endpoint
        @app.get("/metrics")
        def metrics_route():
            return metrics_endpoint()

        client = TestClient(app)
        client.get("/test1")
        client.post("/test2")

        response = client.get("/metrics")
        assert response.status_code == 200

        body = response.text
        # Check for HTTP metrics
        assert "http_requests_total" in body


class TestDBMetricsWrapper:
    """Tests for DBMetricsWrapper."""

    @pytest.mark.anyio
    async def test_db_metrics_wrapper_tracks_duration(self):
        """Test that DB metrics wrapper tracks operation duration."""
        import time

        # Set region for test
        set_region("us-east-1")

        # Track a simulated DB operation
        with db_metrics.track("test_query"):
            time.sleep(0.01)  # Simulate a slow query

        # Check metrics were recorded
        metrics_output = generate_latest(metrics.registry).decode("utf-8")

        # Should have db_query_duration_seconds metric with region
        assert "db_query_duration_seconds" in metrics_output
        assert 'operation="test_query"' in metrics_output
        assert "region=" in metrics_output

        # Clean up
        set_region("")

    @pytest.mark.anyio
    async def test_db_metrics_wrapper_tracks_success(self):
        """Test that DB metrics wrapper tracks successful operations."""
        set_region("us-east-1")

        with db_metrics.track("success_query"):
            pass  # Successful operation

        metrics_output = generate_latest(metrics.registry).decode("utf-8")

        # Should have success counter with region
        # Prometheus label order is not guaranteed
        assert "db_queries_total{" in metrics_output
        assert 'operation="success_query"' in metrics_output
        assert 'status="success"' in metrics_output
        assert "region=" in metrics_output

        # Clean up
        set_region("")

    @pytest.mark.anyio
    async def test_db_metrics_wrapper_tracks_error(self):
        """Test that DB metrics wrapper tracks failed operations."""
        set_region("us-east-1")

        with pytest.raises(ValueError):
            with db_metrics.track("error_query"):
                raise ValueError("DB error")

        metrics_output = generate_latest(metrics.registry).decode("utf-8")

        # Should have error counter with region
        # Prometheus label order is not guaranteed
        assert "db_queries_total{" in metrics_output
        assert 'operation="error_query"' in metrics_output
        assert 'status="error"' in metrics_output
        assert "region=" in metrics_output

        # Clean up
        set_region("")


class TestExtractRequestContext:
    """Tests for extract_request_context helper."""

    @pytest.mark.anyio
    async def test_extract_context_returns_default_values(self):
        """Test that extract_request_context returns defaults for new request."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.get("/test")
        async def test_route(request: Request):
            return extract_request_context(request)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        context = response.json()
        assert context["request_id"] != ""  # Should have request ID
        assert context["user_id"] == "anonymous"  # Default
        assert context["region"] != ""  # Should have region from settings

    @pytest.mark.anyio
    async def test_extract_context_includes_user_from_state(self):
        """Test that extract_request_context includes user from request.state."""
        app = FastAPI()
        app.add_middleware(ObservabilityMiddleware)

        @app.middleware("http")
        async def add_user_to_state(request: Request, call_next):
            # Simulate authentication middleware
            request.state.user = {"sub": "user-123"}
            response = await call_next(request)
            return response

        @app.get("/test")
        async def test_route(request: Request):
            return extract_request_context(request)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        context = response.json()
        assert context["request_id"] != ""
        assert context["user_id"] == "user-123"
        assert context["region"] != ""  # Should have region from settings


class TestCompilerMetrics:
    """Tests for compiler metrics integration."""

    @pytest.mark.anyio
    async def test_compiler_metrics_recorded_on_success(self, async_db_session):
        """Test that compiler metrics are recorded on successful compilation."""
        from uuid import uuid7

        from app.compiler.compiler import compile_ruleset
        from app.db.models import (
            Rule,
            RuleField,
            RuleSet,
            RuleSetVersion,
            RuleSetVersionRule,
            RuleVersion,
        )
        from app.domain.enums import EntityStatus, RuleType

        # Create a rule field (use unique key to avoid conflict with seeded data)
        field = RuleField(
            field_key="test_metric_amount",
            field_id=27,
            display_name="Test Amount",
            description=None,
            data_type="NUMBER",
            allowed_operators=["GT", "LT", "EQ"],
            multi_value_allowed=False,
            is_sensitive=False,
            current_version=1,
            version=1,
            created_by="test@example.com",
        )
        async_db_session.add(field)
        await async_db_session.flush()

        # Create a rule with all required fields
        rule_id = uuid7()
        rule = Rule(
            rule_id=rule_id,
            rule_name="Test Rule",
            description="Test rule for metrics",
            rule_type=RuleType.MONITORING.value,
            current_version=1,
            status=EntityStatus.APPROVED.value,
            created_by="test-user",
        )
        async_db_session.add(rule)
        await async_db_session.flush()

        # Create rule version with approved_by and approved_at for APPROVED status
        from datetime import datetime

        now = datetime.now(UTC)
        rule_version_id = uuid7()
        rule_version = RuleVersion(
            rule_version_id=rule_version_id,
            rule_id=rule_id,
            version=1,
            condition_tree={"field": "test_metric_amount", "op": "GT", "value": 100},
            priority=100,
            status=EntityStatus.APPROVED.value,
            created_by="test-user",
            approved_by="checker-user",
            approved_at=now,
        )
        async_db_session.add(rule_version)
        await async_db_session.flush()

        # Create RuleSet identity (no version/status - those are on RuleSetVersion)
        ruleset_id = uuid7()
        ruleset = RuleSet(
            ruleset_id=ruleset_id,
            environment="test",
            region="AMERICAS",
            country="US",
            rule_type=RuleType.MONITORING.value,
            name="Test RuleSet",
            description="Test ruleset for metrics",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create ACTIVE RuleSetVersion (compiler needs ACTIVE status)
        ruleset_version_id = uuid7()
        ruleset_version = RuleSetVersion(
            ruleset_version_id=ruleset_version_id,
            ruleset_id=ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            created_by="test-user",
            approved_by="checker-user",
            approved_at=now,
            activated_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        # Attach rule to ruleset version
        ruleset_rule = RuleSetVersionRule(
            ruleset_version_id=ruleset_version_id,
            rule_version_id=rule_version_id,
        )
        async_db_session.add(ruleset_rule)
        await async_db_session.commit()

        # Get initial compiler success metric value
        initial_metrics = generate_latest(metrics.registry).decode("utf-8")
        # Extract the current value of compiler_compilations_total for success status
        initial_value = 0
        for line in initial_metrics.split("\n"):
            if "compiler_compilations_total{" in line and 'status="success"' in line:
                # Format: compiler_compilations_total{...} N.N
                parts = line.split("}")
                if len(parts) > 1:
                    try:
                        initial_value = float(parts[1].strip())
                    except (ValueError, IndexError):
                        initial_value = 0
                break

        # Compile the ruleset
        result = await compile_ruleset(ruleset_id, async_db_session)

        assert result is not None
        assert result["rulesetId"] == str(ruleset_id)
        assert len(result["rules"]) == 1

        # Check metrics were recorded
        final_metrics = generate_latest(metrics.registry).decode("utf-8")

        # Extract the final value
        final_value = 0
        for line in final_metrics.split("\n"):
            if "compiler_compilations_total{" in line and 'status="success"' in line:
                parts = line.split("}")
                if len(parts) > 1:
                    try:
                        final_value = float(parts[1].strip())
                    except (ValueError, IndexError):
                        final_value = 0
                break

        # Should have incremented the success counter
        assert final_value > initial_value

        # Check other compiler metrics exist with region label
        assert "compiler_duration_seconds" in final_metrics
        assert "compiler_rules_count" in final_metrics
        assert "compiler_ast_bytes" in final_metrics
        # Check that region label is present in compiler metrics
        assert "region=" in final_metrics
