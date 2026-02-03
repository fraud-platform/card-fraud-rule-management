"""Unit tests for test_utils endpoint.

Tests the /test-token endpoint which generates real Auth0 tokens for local development.
Coverage targets: 80%+ for app/api/routes/test_utils.py
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


class TestGenerateTestToken:
    """Test suite for generate_test_token endpoint."""

    @pytest.mark.anyio
    async def test_returns_403_in_production_environment(self):
        """Test that production environment returns 403 Forbidden."""
        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "prod"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 403
            data = response.json()
            # HTTPException handler wraps detail in "message" field
            assert "not available in production" in data.get("message", str(data.get("detail", "")))

    @pytest.mark.anyio
    async def test_returns_500_when_auth0_credentials_not_configured(self):
        """Test that missing Auth0 credentials returns 500 Internal Server Error."""
        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = None
            mock_settings.auth0_client_secret = None

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            # When detail is a dict, it gets wrapped in message
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Test endpoint not configured"
                assert "Contact administrator" in data["message"]["message"]
            else:
                # Fallback for different error format
                assert "Test endpoint not configured" in str(data)

    @pytest.mark.anyio
    async def test_returns_500_when_client_id_missing_only(self):
        """Test that missing client_id (with secret set) returns 500."""
        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = None
            mock_settings.auth0_client_secret = "test-secret"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Test endpoint not configured"
            else:
                assert "Test endpoint not configured" in str(data)

    @pytest.mark.anyio
    async def test_returns_500_when_client_secret_missing_only(self):
        """Test that missing client_secret (with client_id set) returns 500."""
        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = None

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Test endpoint not configured"
            else:
                assert "Test endpoint not configured" in str(data)

    @pytest.mark.anyio
    async def test_returns_500_when_credentials_empty_strings(self):
        """Test that empty string credentials are treated as missing."""
        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = ""
            mock_settings.auth0_client_secret = ""

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Test endpoint not configured"
            else:
                assert "Test endpoint not configured" in str(data)

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_returns_token_successfully_when_configured(self, mock_httpx_client_class):
        """Test successful token generation with valid credentials."""
        # Mock Auth0 response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert data["token_type"] == "Bearer"
            assert data["expires_in"] == 3600
            assert "issued_at" in data
            assert "usage" in data
            assert "swagger_ui" in data["usage"]
            assert "curl_example" in data["usage"]

            # Verify httpx.AsyncClient was called with timeout
            mock_httpx_client_class.assert_called_once_with(timeout=10.0)

            # Verify the POST request was made to correct URL
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            assert "test.auth0.com" in call_args[0][0]
            assert "/oauth/token" in call_args[0][0]

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_handles_http_status_error_from_auth0(self, mock_httpx_client_class):
        """Test handling of HTTPStatusError when Auth0 request fails."""
        # Mock Auth0 error response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_error = httpx.HTTPStatusError(
            "Invalid credentials", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status = Mock(side_effect=mock_error)

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "bad-client-id"
            mock_settings.auth0_client_secret = "bad-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Authentication service unavailable"
                assert "Auth0" in data["message"]["message"]
            else:
                assert "Authentication service unavailable" in str(data) or "Auth0" in str(data)

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_handles_generic_exception_from_auth0(self, mock_httpx_client_class):
        """Test handling of generic exceptions during token generation."""
        # Mock a generic exception (e.g., network error)
        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(side_effect=Exception("Network error"))

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Failed to get token from Auth0"
                assert "Network error" in data["message"]["message"]
            else:
                assert "Failed to get token from Auth0" in str(data) or "Network error" in str(data)

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_handles_timeout_exception(self, mock_httpx_client_class):
        """Test handling of timeout exceptions during Auth0 request."""
        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out", request=Mock())
        )

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Failed to get token from Auth0"
            else:
                assert (
                    "Failed to get token from Auth0" in str(data)
                    or "timed out" in str(data).lower()
                )

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_token_preview_logging_redacts_jwt(self, mock_httpx_client_class, caplog):
        """Test that token preview in logs only shows first 20 characters."""
        # Mock Auth0 response with a long token
        long_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9." * 10 + "signature"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": long_token,
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            with caplog.at_level("INFO"):
                response = client.get("/api/v1/test-token")

            assert response.status_code == 200

            # Check that a log entry contains redacted token preview
            log_messages = [record.message for record in caplog.records]
            token_log = [msg for msg in log_messages if "Generated M2M test token" in msg]
            assert len(token_log) > 0
            # Verify token is redacted (only shows first 20 chars + ...)
            assert "..." in token_log[0]
            # Full token should NOT appear in logs
            assert long_token not in token_log[0]

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_short_token_not_redacted_in_logs(self, mock_httpx_client_class, caplog):
        """Test that very short tokens are fully redacted in logs."""
        # Mock Auth0 response with a short token (< 20 chars)
        short_token = "short.token.here"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": short_token,
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            with caplog.at_level("INFO"):
                response = client.get("/api/v1/test-token")

            assert response.status_code == 200

            # Check that short tokens are redacted as "***"
            log_messages = [record.message for record in caplog.records]
            token_log = [msg for msg in log_messages if "Generated M2M test token" in msg]
            assert len(token_log) > 0
            assert "***" in token_log[0]
            # Short token should NOT appear in logs
            assert short_token not in token_log[0]

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_payload_sent_to_auth0(self, mock_httpx_client_class):
        """Test that correct payload is sent to Auth0."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        client_id = "my-test-client"
        client_secret = "my-test-secret"
        audience = "https://my-api"
        domain = "mydomain.auth0.com"

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = client_id
            mock_settings.auth0_client_secret = client_secret
            mock_settings.auth0_domain = domain
            mock_settings.auth0_audience = audience

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 200

            # Verify the POST request payload
            call_args = mock_client_instance.post.call_args
            payload = call_args[1]["json"]  # keyword argument 'json'

            assert payload["client_id"] == client_id
            assert payload["client_secret"] == client_secret
            assert payload["audience"] == audience
            assert payload["grant_type"] == "client_credentials"

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_returns_default_values_when_auth0_omits_fields(self, mock_httpx_client_class):
        """Test handling of Auth0 response with missing optional fields."""
        # Mock Auth0 response with only required fields
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "minimal-token",
            # token_type and expires_in are missing
        }
        mock_response.raise_for_status = Mock()

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 200
            data = response.json()
            assert data["access_token"] == "minimal-token"
            # Should use defaults from .get() calls
            assert data["token_type"] == "Bearer"
            assert data["expires_in"] == 86400
            assert "issued_at" in data

    @pytest.mark.anyio
    async def test_works_in_test_environment(self):
        """Test that endpoint works in test environment (not just local)."""
        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "test"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            # Should not raise 403 in test environment
            # It will fail with 500 because we're not mocking httpx, but we're
            # just checking it doesn't return 403
            with patch("app.api.routes.test_utils.httpx.AsyncClient") as mock_httpx_client_class:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "access_token": "test-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                mock_response.raise_for_status = Mock()

                mock_client_instance = MagicMock()
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client_instance.post = AsyncMock(return_value=mock_response)

                mock_httpx_client_class.return_value = mock_client_instance

                from app.main import create_app

                app = create_app()
                client = TestClient(app)

                response = client.get("/api/v1/test-token")

                # Should not be 403 (forbidden in production)
                assert response.status_code != 403
                assert response.status_code == 200

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_auth0_403_error_handling(self, mock_httpx_client_class):
        """Test handling of Auth0 403 Forbidden errors."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_error = httpx.HTTPStatusError("Forbidden", request=Mock(), response=mock_response)
        mock_response.raise_for_status = Mock(side_effect=mock_error)

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            # Should not leak Auth0 error details
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Authentication service unavailable"
            else:
                assert "Authentication service unavailable" in str(data)

    @patch("app.api.routes.test_utils.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_auth0_500_error_handling(self, mock_httpx_client_class):
        """Test handling of Auth0 500 Internal Server errors."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_error = httpx.HTTPStatusError(
            "Internal Server Error", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status = Mock(side_effect=mock_error)

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post = AsyncMock(return_value=mock_response)

        mock_httpx_client_class.return_value = mock_client_instance

        with patch("app.api.routes.test_utils.settings") as mock_settings:
            mock_settings.app_env = "local"
            mock_settings.auth0_client_id = "test-client-id"
            mock_settings.auth0_client_secret = "test-client-secret"
            mock_settings.auth0_domain = "test.auth0.com"
            mock_settings.auth0_audience = "https://test-api"

            from app.main import create_app

            app = create_app()
            client = TestClient(app)

            response = client.get("/api/v1/test-token")

            assert response.status_code == 500
            data = response.json()
            if "message" in data and isinstance(data["message"], dict):
                assert data["message"]["error"] == "Authentication service unavailable"
            else:
                assert "Authentication service unavailable" in str(data)
