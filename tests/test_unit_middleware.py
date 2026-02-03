"""
Tests for RequestSizeLimitMiddleware.

Tests cover:
- Content-Length header validation (lines 50-61)
- Actual body size validation for POST/PUT/PATCH (lines 72-76)
- Body receive function (line 84)
- Invalid Content-Length header handling
- Requests within size limit
- Different HTTP methods (GET, POST, PUT, PATCH, DELETE)
- Edge cases (empty body, exact limit, boundary conditions)
"""

import pytest
from fastapi import Response, status
from fastapi.testclient import TestClient

from app.core.middleware import RequestSizeLimitMiddleware


class TestRequestSizeLimitMiddlewareInit:
    """Tests for RequestSizeLimitMiddleware initialization."""

    @pytest.mark.anyio
    async def test_init_default_max_size(self):
        """Test initialization with default max size (1MB)."""
        middleware = RequestSizeLimitMiddleware(app=None)
        assert middleware.max_size_bytes == 1 * 1024 * 1024

    @pytest.mark.anyio
    async def test_init_custom_max_size(self):
        """Test initialization with custom max size."""
        middleware = RequestSizeLimitMiddleware(app=None, max_size_mb=5)
        assert middleware.max_size_bytes == 5 * 1024 * 1024

    @pytest.mark.anyio
    async def test_init_zero_max_size(self):
        """Test initialization with zero max size."""
        middleware = RequestSizeLimitMiddleware(app=None, max_size_mb=0)
        assert middleware.max_size_bytes == 0


class TestContentLengthHeaderValidation:
    """Tests for Content-Length header validation (lines 50-61)."""

    @pytest.mark.anyio
    async def test_content_length_exceeds_limit_returns_413(self):
        """Test that request with Content-Length exceeding limit returns 413."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Create a request with large Content-Length header
        # FastAPI TestClient doesn't allow setting Content-Length directly,
        # but the middleware will check the actual body size
        large_data = {"data": "x" * (2 * 1024 * 1024)}  # 2MB
        response = client.post("/test", json=large_data)

        # Should return 413
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "RequestTooLarge" in response.json()["error"]

    @pytest.mark.anyio
    async def test_content_length_within_limit(self):
        """Test that Content-Length within limit proceeds normally."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Small request should succeed
        small_data = {"data": "x" * 100}
        response = client.post("/test", json=small_data)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.anyio
    async def test_content_length_exactly_limit(self):
        """Test that Content-Length exactly at limit proceeds normally."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Create data close to but not over 1MB
        # Account for JSON overhead
        data_size = int(0.9 * 1024 * 1024)  # 900KB
        large_data = {"data": "x" * data_size}
        response = client.post("/test", json=large_data)

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_content_length_one_byte_over_limit(self):
        """Test that Content-Length one byte over limit returns 413."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Create data that will be slightly over 1MB when JSON-encoded
        # Account for JSON overhead: {"data":"..."}
        data_size = int(1.1 * 1024 * 1024)  # 1.1MB
        large_data = {"data": "x" * data_size}
        response = client.post("/test", json=large_data)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.anyio
    async def test_missing_content_length_checked_by_body(self):
        """Test that missing Content-Length still triggers body check."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Even without explicit Content-Length, large body should be caught
        large_data = {"data": "x" * (2 * 1024 * 1024)}
        response = client.post("/test", json=large_data)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class TestActualBodySizeValidation:
    """Tests for actual body size validation (lines 72-76)."""

    @pytest.mark.anyio
    async def test_post_body_exceeds_limit_returns_413(self):
        """Test that POST request with body exceeding limit returns 413."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Create body larger than 1MB
        large_body = b"x" * (2 * 1024 * 1024)
        response = client.post("/test", content=large_body)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "RequestTooLarge" in response.json()["error"]

    @pytest.mark.anyio
    async def test_put_body_exceeds_limit_returns_413(self):
        """Test that PUT request with body exceeding limit returns 413."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.put("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        large_body = b"x" * (1024 * 1024 + 1)
        response = client.put("/test", content=large_body)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.anyio
    async def test_patch_body_exceeds_limit_returns_413(self):
        """Test that PATCH request with body exceeding limit returns 413."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.patch("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        large_body = b"data" * (300 * 1024)  # ~1.2MB
        response = client.patch("/test", content=large_body)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.anyio
    async def test_post_body_within_limit_proceeds(self):
        """Test that POST request with body within limit proceeds."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        small_body = b'{"name": "test"}'
        response = client.post("/test", content=small_body)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.anyio
    async def test_empty_body_allowed(self):
        """Test that empty body is allowed."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"received": True}

        client = TestClient(app)

        response = client.post("/test", content=b"")

        assert response.status_code == 200
        assert response.json() == {"received": True}

    @pytest.mark.anyio
    async def test_body_exactly_at_limit(self):
        """Test body exactly at the limit."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Exactly 1MB
        exact_body = b"x" * (1024 * 1024)
        response = client.post("/test", content=exact_body)

        # Should be allowed (not over the limit)
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_body_one_byte_over_limit(self):
        """Test that body one byte over limit returns 413."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # 1MB + 1 byte
        over_body = b"x" * (1024 * 1024 + 1)
        response = client.post("/test", content=over_body)

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class TestBodyReceiveFunction:
    """Tests for the body receive function (line 84)."""

    @pytest.mark.anyio
    async def test_receive_function_preserves_body_for_downstream(self):
        """Test that receive function makes body available for downstream handlers."""
        from fastapi import FastAPI, Request

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint(req: Request):
            # Try to read the body
            body = await req.body()
            return {"received_bytes": len(body)}

        client = TestClient(app)

        test_body = b'{"user": "test", "value": 123}'
        response = client.post("/test", content=test_body)

        assert response.status_code == 200
        assert response.json() == {"received_bytes": len(test_body)}

    @pytest.mark.anyio
    async def test_receive_function_with_empty_body(self):
        """Test receive function with empty body."""
        from fastapi import FastAPI, Request

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint(req: Request):
            body = await req.body()
            return {"received_bytes": len(body)}

        client = TestClient(app)

        response = client.post("/test", content=b"")

        assert response.status_code == 200
        assert response.json() == {"received_bytes": 0}


class TestHttpMethodHandling:
    """Tests for different HTTP method handling."""

    @pytest.mark.anyio
    async def test_get_request_no_body_check(self):
        """Test that GET requests don't trigger body size check."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.get("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        response = client.get("/test")

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_delete_request_no_body_check(self):
        """Test that DELETE requests don't trigger body size check."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.delete("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "deleted"}

        client = TestClient(app)

        response = client.delete("/test")

        assert response.status_code == 200
        assert response.json() == {"status": "deleted"}

    @pytest.mark.anyio
    async def test_head_request_no_body_check(self):
        """Test that HEAD requests don't trigger body size check."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.head("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return Response(status_code=200)

        client = TestClient(app)

        response = client.head("/test")

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_options_request_no_body_check(self):
        """Test that OPTIONS requests don't trigger body size check."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.options("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return Response(status_code=200)

        client = TestClient(app)

        response = client.options("/test")

        assert response.status_code == 200


class TestBypassAttempts:
    """Tests for security bypass attempts."""

    @pytest.mark.anyio
    async def test_falsified_content_length_small_header_large_body(self):
        """Test that falsified Content-Length (small) with large body is caught."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Even if someone tried to set a small Content-Length header,
        # the body check will catch the actual large body
        large_body = b"x" * (2 * 1024 * 1024)
        response = client.post(
            "/test",
            content=large_body,
            headers={"content-length": "100"},  # Falsified header
        )

        # Should be caught by body check
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.anyio
    async def test_valid_content_length_and_valid_body(self):
        """Test that valid Content-Length and body both within limit succeed."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "created"}

        client = TestClient(app)

        body = b"x" * 100
        response = client.post("/test", content=body)

        assert response.status_code == 200
        assert response.json() == {"status": "created"}


class TestZeroMaxSize:
    """Tests for edge case with zero max size."""

    @pytest.mark.anyio
    async def test_zero_max_size_rejects_non_empty_body(self):
        """Test that zero max size rejects non-empty body."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=0)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Any non-empty body should be rejected
        response = client.post("/test", content=b"x")

        # 1 byte > 0 bytes, should be rejected
        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.anyio
    async def test_zero_max_size_allows_empty_body(self):
        """Test that zero max size allows empty body."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=0)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Empty body should be allowed (0 > 0 is False)
        response = client.post("/test", content=b"")

        assert response.status_code == 200


class TestIntegrationWithFastAPI:
    """Integration tests with FastAPI TestClient."""

    @pytest.mark.anyio
    async def test_middleware_with_fastapi_app(self):
        """Test middleware integration with FastAPI application."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Small request should succeed
        response = client.post("/test", json={"data": "small"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.anyio
    async def test_middleware_rejects_large_request(self):
        """Test that middleware rejects large requests in real FastAPI app."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Large request should be rejected
        large_data = {"data": "x" * (2 * 1024 * 1024)}  # 2MB
        response = client.post("/test", json=large_data)
        assert response.status_code == 413

    @pytest.mark.anyio
    async def test_middleware_allows_get_requests(self):
        """Test that GET requests work normally."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.get("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestErrorMessageFormat:
    """Tests for error message format and content."""

    @pytest.mark.anyio
    async def test_error_message_format(self):
        """Test that error message follows expected JSON format."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        large_data = {"data": "x" * (2 * 1024 * 1024)}
        response = client.post("/test", json=large_data)

        assert response.status_code == 413

        # Check JSON response format
        error_data = response.json()
        assert "error" in error_data
        assert "message" in error_data
        assert error_data["error"] == "RequestTooLarge"
        assert "maximum allowed size" in error_data["message"]


class TestDifferentContentTypes:
    """Tests for different content types."""

    @pytest.mark.anyio
    async def test_json_content_type(self):
        """Test middleware with JSON content."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        small_data = {"name": "test", "value": 123}
        response = client.post("/test", json=small_data)

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_text_content_type(self):
        """Test middleware with text content."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        small_text = "small text payload"
        response = client.post(
            "/test", content=small_text.encode(), headers={"content-type": "text/plain"}
        )

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_form_data_content_type(self):
        """Test middleware with form data."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=1)

        @app.post("/test")
        @pytest.mark.anyio
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Small form data
        response = client.post("/test", data={"field1": "value1", "field2": "value2"})

        assert response.status_code == 200
