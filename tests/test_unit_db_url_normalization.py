"""Unit tests for database URL normalization.

These tests focus on asyncpg runtime URL normalization used by the async engine.
"""

from app.core.db import _normalize_asyncpg_runtime_url


def test_normalize_asyncpg_runtime_url_strips_sslmode_and_preserves_other_params():
    url = "postgresql+asyncpg://user:pass@host:5432/db?sslmode=require&channel_binding=require"
    runtime_url, ssl_enabled = _normalize_asyncpg_runtime_url(url)

    assert "sslmode=" not in runtime_url
    assert "channel_binding=require" in runtime_url
    assert ssl_enabled is True


def test_normalize_asyncpg_runtime_url_disable_maps_to_ssl_false():
    url = "postgresql+asyncpg://user:pass@host:5432/db?sslmode=disable"
    runtime_url, ssl_enabled = _normalize_asyncpg_runtime_url(url)

    assert "sslmode=" not in runtime_url
    assert ssl_enabled is False


def test_normalize_asyncpg_runtime_url_prefer_warns_and_leaves_ssl_unset(caplog):
    url = "postgresql+asyncpg://user:pass@host:5432/db?sslmode=prefer"

    runtime_url, ssl_enabled = _normalize_asyncpg_runtime_url(url)

    assert "sslmode=" not in runtime_url
    assert ssl_enabled is None

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("sslmode" in r.getMessage() for r in warnings)
