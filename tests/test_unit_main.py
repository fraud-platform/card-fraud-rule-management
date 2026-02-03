import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.errors import ForbiddenError, NotFoundError
from app.main import create_app


class TestExceptionHandlers:
    @pytest.mark.anyio
    async def test_domain_error_handler(self):
        app = create_app()
        client = TestClient(app)

        # Add a test route that raises a domain error
        @app.get("/test-error")
        def test_error():
            raise NotFoundError("Test not found", details={"id": 123})

        response = client.get("/test-error")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"
        assert data["message"] == "Test not found"
        assert data["details"]["id"] == 123

    @pytest.mark.anyio
    async def test_forbidden_error_handler(self):
        app = create_app()
        client = TestClient(app)

        @app.get("/test-forbidden")
        def test_forbidden():
            raise ForbiddenError("Access denied", details={"required_role": "ADMIN"})

        response = client.get("/test-forbidden")
        assert response.status_code == 403
        data = response.json()
        assert data["error"] == "ForbiddenError"
        assert data["message"] == "Access denied"

    @pytest.mark.anyio
    async def test_http_exception_handler(self):
        app = create_app()
        client = TestClient(app)

        @app.get("/test-http")
        def test_http():
            raise HTTPException(status_code=400, detail="Bad request")

        response = client.get("/test-http")
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "HTTPException"
        assert data["message"] == "Bad request"

    @pytest.mark.anyio
    async def test_general_exception_handler(self):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        @app.get("/test-general")
        def test_general():
            raise RuntimeError("Unexpected error")

        response = client.get("/test-general")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "InternalServerError"
        assert data["message"] == "An unexpected error occurred"


class TestAppCreation:
    @pytest.mark.anyio
    async def test_create_app_registers_routers(self):
        app = create_app()

        # Check that routers are registered
        routes = [route.path for route in app.routes]
        assert "/api/v1/health" in routes
        assert "/api/v1/rule-fields" in routes
        assert "/api/v1/rules" in routes
        assert "/api/v1/approvals" in routes
        assert "/api/v1/rulesets" in routes

    @pytest.mark.anyio
    async def test_app_has_cors_middleware(self):
        app = create_app()

        cors_middleware = None
        for middleware in app.user_middleware:
            if hasattr(middleware, "cls") and "CORSMiddleware" in str(middleware.cls):
                cors_middleware = middleware
                break

        assert cors_middleware is not None

    @pytest.mark.anyio
    async def test_app_metadata(self):
        app = create_app()

        assert app.title == "Fraud Governance API"
        assert app.version == "0.1.0"
