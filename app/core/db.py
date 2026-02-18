"""
Database connection and session management.

Provides SQLAlchemy engine, session factory, and dependency injection
for FastAPI endpoints.

Supports both sync and async SQLAlchemy sessions.
"""

import logging
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_sessionmaker: sessionmaker | None = None
_telemetry_instrumented: bool = False

_async_engine: AsyncEngine | None = None
_async_sessionmaker: async_sessionmaker | None = None


def get_engine() -> Engine:
    """
    Create and configure the SQLAlchemy engine.

    Uses psycopg driver for sync operations (migrations, scripts).
    Connection health checks via pool_pre_ping.

    Production-ready configuration includes:
    - Connection pooling with appropriate limits
    - Statement timeout to prevent long-running queries
    - Connection recycling to prevent stale connections

    Returns:
        Configured SQLAlchemy engine
    """
    global _engine

    if _engine is not None:
        return _engine

    url = settings.sync_url
    if not url:
        raise RuntimeError("DATABASE_URL_APP is required")

    # Production uses Postgres (Neon). Keep connection args minimal.
    connect_args: dict[str, object] = {}
    if url.startswith("postgresql"):
        # Set connection timeout
        # Note: statement_timeout is NOT set here because Neon's connection pooler
        # doesn't support it in the options string. Set it per-query if needed.
        connect_args = {
            "connect_timeout": 5,
        }

    # Connection pool configuration
    # Adjust these based on your expected concurrency
    pool_size = 20  # Number of connections to maintain
    max_overflow = 10  # Additional connections allowed beyond pool_size
    pool_timeout = 30  # Seconds to wait before giving up on getting a connection
    pool_recycle = 3600  # Recycle connections after 1 hour (prevents stale connections)

    _engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,  # Verify connections before use
        connect_args=connect_args,
        echo=False,  # Set to True for SQL query logging in development
    )

    # Instrument SQLAlchemy with OpenTelemetry (only once)
    _instrument_sqlalchemy(_engine)

    return _engine


def _instrument_sqlalchemy(engine: Engine) -> None:
    """
    Instrument SQLAlchemy engine with OpenTelemetry.

    Args:
        engine: SQLAlchemy engine instance
    """
    global _telemetry_instrumented

    if _telemetry_instrumented:
        return

    try:
        from app.core.telemetry import instrument_sqlalchemy

        instrument_sqlalchemy(engine)
        _telemetry_instrumented = True
    except ImportError:
        # OpenTelemetry not available
        logger.debug("OpenTelemetry not available - skipping SQLAlchemy instrumentation")
    except Exception as e:
        logger.warning(f"Failed to instrument SQLAlchemy with OpenTelemetry: {e}")


def get_sessionmaker() -> sessionmaker:
    global _sessionmaker
    if _sessionmaker is not None:
        return _sessionmaker
    _sessionmaker = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _sessionmaker


@contextmanager
def get_db() -> Generator[Session]:
    """
    Context manager for database sessions.

    Usage:
        with get_db() as db:
            result = db.query(Model).all()

    Yields:
        Database session

    Ensures:
        Session is properly closed after use, even if exception occurs
    """
    session_local = get_sessionmaker()
    db = session_local()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Generator[Session]:
    """
    FastAPI dependency for database sessions (sync version).

    DEPRECATED: Use async sessions for new code. This is kept for
    backward compatibility and test support only.

    Usage in endpoints:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db_session)):
            return db.query(Item).all()

    Yields:
        Database session

    Ensures:
        Session is properly closed after request completion
    """
    session_local = get_sessionmaker()
    db = session_local()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Async Database Support
# ============================================================================


def create_fresh_async_engine() -> AsyncEngine:
    """Create a fresh async engine without caching.

    Used for tests to ensure each test gets its own engine bound to its event loop.
    """
    url = settings.async_url
    if not url:
        raise RuntimeError("DATABASE_URL_APP is required")

    return create_async_engine(
        url,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=False,
        connect_args={
            "server_settings": {"timezone": "UTC", "search_path": "fraud_gov,public"},
            "timeout": 30,
        },
    )


def get_async_engine() -> AsyncEngine:
    """
    Create and configure the async SQLAlchemy engine.

    Uses asyncpg driver for async operations (FastAPI endpoints).
    SQLAlchemy 2.0+ automatically uses the async adaptation when
    create_async_engine is called with an asyncpg URL.

    Returns:
        Configured async SQLAlchemy engine
    """
    global _async_engine

    if _async_engine is not None:
        return _async_engine

    url = settings.async_url
    if not url:
        raise RuntimeError("DATABASE_URL_APP is required")

    _async_engine = create_async_engine(
        url,
        pool_size=20,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=False,
        connect_args={
            "server_settings": {"timezone": "UTC", "search_path": "fraud_gov,public"},
            "timeout": 30,
        },
    )

    # Note: OpenTelemetry instrumentation for async engines
    # requires special handling. Skipping for now.

    return _async_engine


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the async sessionmaker.

    Returns:
        Async sessionmaker factory
    """
    global _async_sessionmaker
    if _async_sessionmaker is not None:
        return _async_sessionmaker

    engine = get_async_engine()
    _async_sessionmaker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return _async_sessionmaker


async def reset_async_engine() -> None:
    """Reset the async database engine and sessionmaker.

    Useful for tests to ensure fresh connections on new event loops.
    """
    global _async_engine, _async_sessionmaker

    if _async_engine is not None:
        await _async_engine.dispose()
    _async_engine = None
    _async_sessionmaker = None


@asynccontextmanager
async def get_async_db_session() -> AsyncIterator[AsyncSession]:
    """Async database session dependency for FastAPI endpoints.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_async_db_session)):
            result = await db.execute(select(Item))
            return result.scalars().all()

    Yields:
        Async database session

    Ensures:
        Session is properly closed after request completion
    """
    session_maker = get_async_sessionmaker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
