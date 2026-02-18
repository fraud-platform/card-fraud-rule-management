"""Unit tests for database URL normalization in settings."""

from app.core.config import Settings


def _make_settings(database_url_app: str) -> Settings:
    return Settings(
        app_env="local",
        app_region="LOCAL",
        database_url_app=database_url_app,
        auth0_domain="https://example.auth0.com",
        auth0_audience="https://fraud-governance-api",
    )


def test_async_url_strips_engine_query_options() -> None:
    """Engine-only options in DATABASE_URL should not be passed to asyncpg connect()."""
    settings = _make_settings(
        "postgresql://user:pass@localhost:5432/fraud_gov"
        "?pool_size=20&max_overflow=10&sslmode=require"
    )

    url = settings.async_url

    assert url.startswith("postgresql+asyncpg://")
    assert "pool_size=" not in url
    assert "max_overflow=" not in url
    assert "sslmode=require" in url


def test_sync_url_strips_engine_query_options() -> None:
    """Sync URL should also drop engine-only options from query params."""
    settings = _make_settings(
        "postgresql+asyncpg://user:pass@localhost:5432/fraud_gov"
        "?pool_size=20&pool_recycle=1800&sslmode=require"
    )

    url = settings.sync_url

    assert url.startswith("postgresql+psycopg://")
    assert "pool_size=" not in url
    assert "pool_recycle=" not in url
    assert "sslmode=require" in url
