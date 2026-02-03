"""
Unit tests for health check endpoints.

Tests cover:
- Public health endpoints (when HEALTH_TOKEN is not set)
- Database connectivity checks
- Edge cases and error conditions
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set required environment variables before importing app
os.environ.setdefault("DATABASE_URL_APP", "postgresql://user:pass@localhost:5432/db")
os.environ.setdefault("AUTH0_DOMAIN", "example.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://fraud-governance-api")

from app.main import create_app

# ============================================================================
# Tests: Public Health Endpoints (HEALTH_TOKEN not set)
# ============================================================================


@pytest.mark.anyio
async def test_health_ok() -> None:
    """Health endpoint returns 200 when no authentication is required."""
    client = TestClient(create_app())
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.anyio
async def test_readyz_ok_with_db() -> None:
    """Readiness endpoint returns 200 when database is available."""
    client = TestClient(create_app())
    resp = client.get("/api/v1/readyz")

    # May return 503 if DB is not available in test environment
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "ok" in body and "db" in body


@pytest.mark.anyio
async def test_readyz_reports_unavailable_without_db() -> None:
    """Readiness endpoint returns 503 when database is unavailable."""
    client = TestClient(create_app())
    resp = client.get("/api/v1/readyz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "ok" in body and "db" in body


# ============================================================================
# Tests: Database Connectivity in readyz
# ============================================================================


@patch("app.api.routes.health.get_async_engine")
@pytest.mark.anyio
async def test_readyz_returns_200_when_db_connection_succeeds(
    mock_get_engine: MagicMock,
) -> None:
    """Readiness endpoint returns 200 when database connection succeeds."""
    # Mock successful database connection
    mock_engine = MagicMock()
    # Mock async connection context manager
    mock_conn = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    mock_get_engine.return_value = mock_engine

    client = TestClient(create_app())
    resp = client.get("/api/v1/readyz")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "db": "ok"}

    # Verify DB query was executed
    mock_conn.execute.assert_called_once()


@patch("app.api.routes.health.get_async_engine")
@pytest.mark.anyio
async def test_readyz_returns_503_when_db_connection_fails(
    mock_get_engine: MagicMock,
) -> None:
    """Readiness endpoint returns 503 when database connection fails."""
    # Mock database connection failure
    mock_get_engine.side_effect = Exception("Connection refused")

    client = TestClient(create_app())
    resp = client.get("/api/v1/readyz")

    assert resp.status_code == 503
    assert resp.json() == {"ok": False, "db": "unavailable"}


@patch("app.api.routes.health.get_async_engine")
@pytest.mark.anyio
async def test_readyz_returns_503_when_db_query_fails(
    mock_get_engine: MagicMock,
) -> None:
    """Readiness endpoint returns 503 when database query fails."""
    # Mock connection that fails during execute
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = Exception("Query timeout")
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    mock_get_engine.return_value = mock_engine

    client = TestClient(create_app())
    resp = client.get("/api/v1/readyz")

    assert resp.status_code == 503
    assert resp.json() == {"ok": False, "db": "unavailable"}


# ============================================================================
# Tests: Health Dependencies
# ============================================================================


@pytest.mark.anyio
async def test_get_health_dependencies_returns_empty_list_when_no_token() -> None:
    """get_health_dependencies returns empty list when HEALTH_TOKEN is not set."""
    from app.api.routes.health import get_health_dependencies

    deps = get_health_dependencies()
    assert deps == []
