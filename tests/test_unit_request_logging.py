"""
Tests for request/response logging middleware.

Tests cover:
- Header sanitization (_sanitize_headers)
- Body sanitization (_sanitize_body)
- Body formatting for logging (_format_body_for_log)
- RequestLoggingMiddleware with various scenarios
- StreamingRequestLoggingMiddleware
- Sensitive data redaction
- Body size truncation
- JSON serialization edge cases
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.request_logging import (
    RequestLoggingMiddleware,
    StreamingRequestLoggingMiddleware,
    _format_body_for_log,
    _sanitize_body,
    _sanitize_headers,
)


class TestSanitizeHeaders:
    """Tests for the _sanitize_headers function."""

    @pytest.mark.anyio
    async def test_sanitize_headers_redacts_authorization(self):
        """Test that authorization header is redacted."""
        headers = {
            "authorization": "Bearer secret-token",
            "content-type": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result["authorization"] == "***REDACTED***"
        assert result["content-type"] == "application/json"

    @pytest.mark.anyio
    async def test_sanitize_headers_redacts_cookie(self):
        """Test that cookie header is redacted."""
        headers = {
            "cookie": "session=abc123",
            "accept": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result["cookie"] == "***REDACTED***"
        assert result["accept"] == "application/json"

    @pytest.mark.anyio
    async def test_sanitize_headers_redacts_set_cookie(self):
        """Test that set-cookie header is redacted."""
        headers = {
            "set-cookie": "session=xyz789",
            "content-type": "text/html",
        }
        result = _sanitize_headers(headers)
        assert result["set-cookie"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_headers_redacts_x_api_key(self):
        """Test that x-api-key header is redacted."""
        headers = {
            "x-api-key": "api-key-123",
            "accept": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result["x-api-key"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_headers_redacts_x_auth_token(self):
        """Test that x-auth-token header is redacted."""
        headers = {
            "x-auth-token": "auth-token-456",
            "content-type": "application/json",
        }
        result = _sanitize_headers(headers)
        assert result["x-auth-token"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_headers_case_insensitive(self):
        """Test that header matching is case-insensitive."""
        headers = {
            "Authorization": "Bearer token",
            "CONTENT-TYPE": "application/json",
            "X-Api-Key": "secret-key",
        }
        result = _sanitize_headers(headers)
        assert result["Authorization"] == "***REDACTED***"
        assert result["CONTENT-TYPE"] == "application/json"
        assert result["X-Api-Key"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_headers_preserves_non_sensitive(self):
        """Test that non-sensitive headers are preserved."""
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "host": "example.com",
        }
        result = _sanitize_headers(headers)
        assert result == headers

    @pytest.mark.anyio
    async def test_sanitize_headers_empty_dict(self):
        """Test with empty headers dict."""
        result = _sanitize_headers({})
        assert result == {}

    @pytest.mark.anyio
    async def test_sanitize_headers_all_sensitive(self):
        """Test when all headers are sensitive."""
        headers = {
            "authorization": "Bearer token",
            "cookie": "session=abc",
            "x-api-key": "key-123",
        }
        result = _sanitize_headers(headers)
        assert all(v == "***REDACTED***" for v in result.values())


class TestSanitizeBody:
    """Tests for the _sanitize_body function."""

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_password(self):
        """Test that password field is redacted."""
        body = {"username": "testuser", "password": "secret123"}
        result = _sanitize_body(body)
        assert result["username"] == "testuser"
        assert result["password"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_token(self):
        """Test that token field is redacted."""
        body = {"user_id": "123", "token": "abc-token-def"}
        result = _sanitize_body(body)
        assert result["user_id"] == "123"
        assert result["token"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_secret(self):
        """Test that secret field is redacted."""
        body = {"app_id": "myapp", "secret": "super-secret"}
        result = _sanitize_body(body)
        assert result["app_id"] == "myapp"
        assert result["secret"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_api_key(self):
        """Test that api_key field is redacted."""
        body = {"name": "test", "api_key": "key-12345"}
        result = _sanitize_body(body)
        assert result["name"] == "test"
        assert result["api_key"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_access_token(self):
        """Test that access_token field is redacted."""
        body = {"refresh": "abc", "access_token": "xyz"}
        result = _sanitize_body(body)
        assert result["refresh"] == "abc"
        assert result["access_token"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_refresh_token(self):
        """Test that refresh_token field is redacted."""
        body = {"access": "abc", "refresh_token": "xyz"}
        result = _sanitize_body(body)
        assert result["access"] == "abc"
        assert result["refresh_token"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_redacts_client_secret(self):
        """Test that client_secret field is redacted."""
        body = {"client_id": "myapp", "client_secret": "secret"}
        result = _sanitize_body(body)
        assert result["client_id"] == "myapp"
        assert result["client_secret"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_case_insensitive(self):
        """Test that field matching is case-insensitive."""
        body = {"Password": "secret", "Token": "abc", "USERNAME": "test"}
        result = _sanitize_body(body)
        assert result["Password"] == "***REDACTED***"
        assert result["Token"] == "***REDACTED***"
        assert result["USERNAME"] == "test"

    @pytest.mark.anyio
    async def test_sanitize_body_nested_dict(self):
        """Test sanitization of nested dictionaries."""
        body = {
            "user": "testuser",
            "credentials": {
                "password": "secret123",
                "api_key": "key-456",
            },
        }
        result = _sanitize_body(body)
        assert result["user"] == "testuser"
        assert result["credentials"]["password"] == "***REDACTED***"
        assert result["credentials"]["api_key"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_list_of_dicts(self):
        """Test sanitization of lists containing dictionaries."""
        body = {
            "users": [
                {"name": "Alice", "password": "pass1"},
                {"name": "Bob", "password": "pass2"},
            ]
        }
        result = _sanitize_body(body)
        assert result["users"][0]["name"] == "Alice"
        assert result["users"][0]["password"] == "***REDACTED***"
        assert result["users"][1]["name"] == "Bob"
        assert result["users"][1]["password"] == "***REDACTED***"

    @pytest.mark.anyio
    async def test_sanitize_body_list_of_primitives(self):
        """Test that lists of primitives are preserved."""
        body = {"ids": [1, 2, 3], "names": ["Alice", "Bob"]}
        result = _sanitize_body(body)
        assert result == body

    @pytest.mark.anyio
    async def test_sanitize_body_empty_dict(self):
        """Test with empty dictionary."""
        result = _sanitize_body({})
        assert result == {}

    @pytest.mark.anyio
    async def test_sanitize_body_none(self):
        """Test with None value."""
        result = _sanitize_body(None)
        assert result is None

    @pytest.mark.anyio
    async def test_sanitize_body_string(self):
        """Test with string value (non-dict)."""
        result = _sanitize_body("plain string")
        assert result == "plain string"

    @pytest.mark.anyio
    async def test_sanitize_body_number(self):
        """Test with numeric value."""
        result = _sanitize_body(42)
        assert result == 42

    @pytest.mark.anyio
    async def test_sanitize_body_deeply_nested(self):
        """Test sanitization of deeply nested structures."""
        body = {
            "level1": {
                "level2": {
                    "level3": {
                        "password": "deep-secret",
                        "value": "keep-me",
                    }
                }
            }
        }
        result = _sanitize_body(body)
        assert result["level1"]["level2"]["level3"]["password"] == "***REDACTED***"
        assert result["level1"]["level2"]["level3"]["value"] == "keep-me"

    @pytest.mark.anyio
    async def test_sanitize_body_mixed_types(self):
        """Test sanitization with mixed data types."""
        body = {
            "string": "value",
            "number": 123,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"password": "secret"},
        }
        result = _sanitize_body(body)
        assert result["string"] == "value"
        assert result["number"] == 123
        assert result["boolean"] is True
        assert result["null"] is None
        assert result["list"] == [1, 2, 3]
        assert result["dict"]["password"] == "***REDACTED***"


class TestFormatBodyForLog:
    """Tests for the _format_body_for_log function."""

    @pytest.mark.anyio
    async def test_format_body_for_log_none(self):
        """Test with None body returns empty string."""
        result = _format_body_for_log(None)
        assert result == ""

    @pytest.mark.anyio
    async def test_format_body_for_log_simple_dict(self):
        """Test formatting of simple dictionary."""
        body = {"name": "test", "value": 123}
        result = _format_body_for_log(body)
        assert '"name": "test"' in result
        assert '"value": 123' in result

    @pytest.mark.anyio
    async def test_format_body_for_log_sanitizes(self):
        """Test that sanitization is applied."""
        body = {"username": "test", "password": "secret"}
        result = _format_body_for_log(body)
        assert '"username": "test"' in result
        assert '"password": "***REDACTED***"' in result

    @pytest.mark.anyio
    async def test_format_body_for_log_truncates_large_body(self):
        """Test that large body is truncated."""
        # Create a body that will exceed default max_size (10000)
        body = {"data": "x" * 15000}
        result = _format_body_for_log(body)
        assert len(result) <= 10000 + len("... (truncated)")
        assert result.endswith("... (truncated)")

    @pytest.mark.anyio
    async def test_format_body_for_log_custom_max_size(self):
        """Test with custom max_size."""
        body = {"data": "x" * 100}
        result = _format_body_for_log(body, max_size=50)
        assert len(result) <= 50 + len("... (truncated)")
        assert result.endswith("... (truncated)")

    @pytest.mark.anyio
    async def test_format_body_for_log_non_serializable(self):
        """Test handling of non-JSON-serializable objects."""
        # Use default=str in json.dumps
        body = {"date": datetime(2024, 1, 1, tzinfo=UTC)}
        result = _format_body_for_log(body)
        assert "2024-01-01" in result

    @pytest.mark.anyio
    async def test_format_body_for_log_serialization_error(self):
        """Test handling when serialization fails."""

        # Create an object that will fail serialization and default=str
        class Unserializable:
            def __str__(self):
                return "unserializable"

        body = {"obj": Unserializable()}
        result = _format_body_for_log(body)
        # Should fall back to str(body)[:max_size]
        assert "unserializable" in result

    @pytest.mark.anyio
    async def test_format_body_for_log_empty_dict(self):
        """Test with empty dictionary."""
        result = _format_body_for_log({})
        assert result == "{}"

    @pytest.mark.anyio
    async def test_format_body_for_log_complex_structure(self):
        """Test with complex nested structure."""
        body = {
            "users": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
            "metadata": {"total": 2, "page": 1},
        }
        result = _format_body_for_log(body)
        assert '"users":' in result
        assert '"metadata":' in result

    @pytest.mark.anyio
    async def test_format_body_for_log_unicode(self):
        """Test with unicode characters."""
        body = {"message": "Hello World"}
        result = _format_body_for_log(body)
        assert "Hello" in result

    @pytest.mark.anyio
    async def test_format_body_for_log_truncation_boundary(self):
        """Test truncation at exact boundary."""
        # Create a body that's exactly at the limit
        body = {"data": "x" * 9990}  # With JSON overhead will be ~10000
        result = _format_body_for_log(body, max_size=10000)
        # Should not truncate if exactly at limit
        assert len(result) <= 10000 + len("... (truncated)")

    @pytest.mark.anyio
    async def test_format_body_for_log_dict_with_sensitive_data(self):
        """Test that both sanitization and truncation work together."""
        body = {"user": "test", "password": "secret", "data": "x" * 15000}
        result = _format_body_for_log(body, max_size=500)
        assert "***REDACTED***" in result
        assert len(result) <= 500 + len("... (truncated)")

    @pytest.mark.anyio
    async def test_format_body_for_log_list(self):
        """Test formatting of a list."""
        body = [1, 2, 3, {"key": "value"}]
        result = _format_body_for_log(body)
        assert "[1, 2, 3," in result


class TestRequestLoggingMiddleware:
    """Tests for the RequestLoggingMiddleware class."""

    @pytest.mark.anyio
    async def test_init_enabled_true(self):
        """Test initialization with enabled=True."""
        middleware = RequestLoggingMiddleware(app=None, enabled=True)
        assert middleware.enabled is True

    @pytest.mark.anyio
    async def test_init_disabled(self, monkeypatch):
        """Test initialization with enabled=False when env is production."""
        from app.core import request_logging

        # Must patch to production env to test enabled=False
        monkeypatch.setattr(request_logging.settings, "app_env", "prod")

        middleware = RequestLoggingMiddleware(app=None, enabled=False)
        assert middleware.enabled is False

    @pytest.mark.anyio
    async def test_init_uses_settings_when_env_local(self, monkeypatch):
        """Test that middleware uses settings.app_env when enabled not explicitly provided."""
        from app.core import request_logging

        # Patch settings to return 'local' environment
        monkeypatch.setattr(request_logging.settings, "app_env", "local")

        middleware = RequestLoggingMiddleware(app=None)
        assert middleware.enabled is True  # local env enables logging

    @pytest.mark.anyio
    async def test_init_uses_settings_when_env_test(self, monkeypatch):
        """Test that test environment enables logging."""
        from app.core import request_logging

        # Patch settings to return 'test' environment
        monkeypatch.setattr(request_logging.settings, "app_env", "test")

        middleware = RequestLoggingMiddleware(app=None)
        assert middleware.enabled is True  # test env enables logging

    @pytest.mark.anyio
    async def test_init_uses_settings_when_env_production(self, monkeypatch):
        """Test that production environment respects enabled=False."""
        from app.core import request_logging

        # Patch settings to return 'production' environment
        monkeypatch.setattr(request_logging.settings, "app_env", "prod")

        middleware = RequestLoggingMiddleware(app=None, enabled=False)
        assert middleware.enabled is False

    @pytest.mark.anyio
    async def test_integration_with_fastapi_client(self, monkeypatch):
        """Test middleware integration with FastAPI TestClient."""
        from app.core import request_logging
        from app.main import create_app

        # Ensure logging is enabled
        monkeypatch.setattr(request_logging.settings, "app_env", "test")

        # Create app and client
        app = create_app()
        client = TestClient(app)

        # Make a request to health endpoint (should be skipped by middleware)
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_sanitizes_headers_in_integration(self, monkeypatch):
        """Test that sensitive headers are redacted in real requests."""
        from app.core import request_logging
        from app.main import create_app

        # Ensure logging is enabled
        monkeypatch.setattr(request_logging.settings, "app_env", "test")

        app = create_app()
        client = TestClient(app)

        # Make a request with authorization header
        response = client.get(
            "/api/v1/health", headers={"Authorization": "Bearer secret-token-123"}
        )
        assert response.status_code == 200


class TestStreamingRequestLoggingMiddleware:
    """Tests for the StreamingRequestLoggingMiddleware class."""

    @pytest.mark.anyio
    async def test_init_enabled_true(self):
        """Test initialization with enabled=True."""
        from app.main import create_app

        app = create_app()
        middleware = StreamingRequestLoggingMiddleware(app=app, enabled=True)
        assert middleware.enabled is True

    @pytest.mark.anyio
    async def test_init_disabled(self, monkeypatch):
        """Test initialization with enabled=False when env is production."""
        from app.core import request_logging
        from app.main import create_app

        # Must patch to production env to test enabled=False
        monkeypatch.setattr(request_logging.settings, "app_env", "prod")

        app = create_app()
        middleware = StreamingRequestLoggingMiddleware(app=app, enabled=False)
        assert middleware.enabled is False

    @pytest.mark.anyio
    async def test_init_uses_settings_when_env_local(self, monkeypatch):
        """Test that middleware uses settings.app_env."""
        from app.core import request_logging
        from app.main import create_app

        # Patch settings to return 'local' environment
        monkeypatch.setattr(request_logging.settings, "app_env", "local")

        app = create_app()
        middleware = StreamingRequestLoggingMiddleware(app=app)
        assert middleware.enabled is True  # local env enables logging

    @pytest.mark.anyio
    async def test_init_uses_settings_when_env_test(self, monkeypatch):
        """Test that test environment enables logging."""
        from app.core import request_logging
        from app.main import create_app

        # Patch settings to return 'test' environment
        monkeypatch.setattr(request_logging.settings, "app_env", "test")

        app = create_app()
        middleware = StreamingRequestLoggingMiddleware(app=app)
        assert middleware.enabled is True

    @pytest.mark.anyio
    async def test_init_uses_settings_when_env_production(self, monkeypatch):
        """Test that production environment respects enabled parameter."""
        from app.core import request_logging
        from app.main import create_app

        # Patch settings to return 'production' environment
        monkeypatch.setattr(request_logging.settings, "app_env", "prod")

        app = create_app()
        middleware = StreamingRequestLoggingMiddleware(app=app, enabled=False)
        assert middleware.enabled is False

    @pytest.mark.anyio
    async def test_integration_with_fastapi_client(self, monkeypatch):
        """Test streaming middleware integration with FastAPI TestClient."""
        from app.core import request_logging
        from app.main import create_app

        # Ensure logging is enabled
        monkeypatch.setattr(request_logging.settings, "app_env", "test")

        # Create app and client
        app = create_app()
        client = TestClient(app)

        # Make a request to health endpoint
        response = client.get("/api/v1/health")
        assert response.status_code == 200
