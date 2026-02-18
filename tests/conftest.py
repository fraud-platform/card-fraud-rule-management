"""
Pytest configuration and shared fixtures for API integration tests.

Provides:
- Test database setup/teardown (sync and async SQLAlchemy)
- Mock Auth0 JWT tokens
- FastAPI TestClient with auth
- Test data factories for rules, fields, and rulesets
- Enhanced logging with JSON formatter
- Request/response logging via logged_client fixture

Async SQLAlchemy Fixtures:
- async_engine: Session-scoped async engine
- async_db_session: Function-scoped async session with transaction rollback
- clean_async_db_session: Function-scoped async session with real commits
- adb_rule_field: Async fixture creating a RuleField
- adb_rule: Async fixture creating a Rule
- adb_ruleset: Async fixture creating a RuleSet

Async Helper Functions:
- acreate_rule_field_in_db(): Create RuleField using AsyncSession
- acreate_rule_in_db(): Create Rule using AsyncSession
- acreate_ruleset_in_db(): Create RuleSet using AsyncSession
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

# Add app to path for imports
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# NOTE: Tests do NOT auto-discover or default-load any .env files.
# If you want to use an env file locally, set ENV_FILE explicitly.
_explicit_env_file = os.environ.get("ENV_FILE", "").strip()
if _explicit_env_file:
    from app.core.dotenv import load_env_file

    load_env_file(_explicit_env_file, overwrite=False)

import httpx  # noqa: E402 (import after path setup)
import pytest  # noqa: E402 (import after path setup)
from fastapi.testclient import TestClient  # noqa: E402 (import after path setup)
from sqlalchemy import create_engine, text  # noqa: E402 (import after path setup)
from sqlalchemy.engine import Engine  # noqa: E402 (import after path setup)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402 (import after path setup)

# Import pytest HTML report module for custom logging and fixtures
# This applies the TestJSONFormatter and provides logged_client fixture
import tests.pytest_html_report  # noqa: E402, F401 (side-effect import for logging config)

# Set test environment variables before importing app
# IMPORTANT: Use Doppler for secrets management (preferred)
if "DATABASE_URL_APP" not in os.environ:
    raise RuntimeError(
        "DATABASE_URL_APP environment variable must be set for testing.\n\n"
        "Recommended options:\n"
        "1. Run with Doppler secrets (REQUIRED for CI/Production): uv run doppler-test\n"
        "2. For local dev without Doppler: Create .env.test file (see .env.example)\n"
        "3. Or set ENV_FILE=.env.test environment variable\n"
    )
os.environ.setdefault("AUTH0_DOMAIN", "test.local")
os.environ.setdefault("AUTH0_AUDIENCE", "test-audience")
os.environ.setdefault("AUTH0_ALGORITHMS", "RS256")

from app.core.db import get_db_session  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402 (import after env setup)
from app.db.models import Base  # noqa: E402 (import after env setup)
from app.main import create_app  # noqa: E402 (import after env setup)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--auth-token",
        action="store",
        default=None,
        help="Bearer token for E2E tests (or set E2E_AUTH_TOKEN env var)",
    )


def pytest_configure() -> None:
    """
    Configure pytest settings.

    On Windows, sets SelectorEventLoop policy for psycopg async compatibility.
    psycopg async cannot use ProactorEventLoop (Windows default).
    """
    if sys.platform == "win32":
        import asyncio

        # Set the event loop policy to use SelectorEventLoop
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        )


@pytest.fixture(scope="session")
def e2e_auth_token(request: pytest.FixtureRequest) -> str | None:
    token = request.config.getoption("--auth-token")
    if token:
        return str(token).strip()
    env_token = os.environ.get("E2E_AUTH_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()
    return None


@pytest.fixture(scope="session")
def e2e_auth_header(e2e_auth_token: str | None) -> dict[str, str] | None:
    if not e2e_auth_token:
        return None
    token = e2e_auth_token
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {"Authorization": token}


# ============================================================================
# Test Database Setup
# ============================================================================


def _is_safe_to_reset_database(database_url: str) -> bool:
    """Return True if it's safe to drop/recreate the fraud_gov schema.

    We only do destructive schema resets when the DB name looks like a dedicated
    test database, or when explicitly opted-in via env var.
    """

    # Very small, dependency-free DB name parsing.
    # Examples:
    #   postgresql+psycopg://user:pass@host:5432/mydb?sslmode=require
    #   postgresql://user:pass@host/mydb
    path = database_url.split("?", 1)[0].rsplit("/", 1)[-1]
    db_name = path.strip().lower()
    return any(token in db_name for token in ("test", "pytest"))


def _pytest_reset_db_enabled() -> bool:
    return os.environ.get("PYTEST_RESET_DB", "").strip().lower() in {"1", "true", "yes"}


def _normalize_db_url_for_psycopg(database_url: str) -> str:
    # Automatically use psycopg v3 (modern driver) instead of psycopg2
    if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _parse_username(database_url: str) -> str | None:
    try:
        parsed = urlparse(database_url)
        return parsed.username
    except Exception:
        return None


def _assert_safe_pg_identifier(identifier: str) -> None:
    # Keep it strict: this is only used for GRANT statements in tests.
    if not identifier:
        raise ValueError("Empty identifier")
    if not (identifier[0].isalpha() or identifier[0] == "_"):
        raise ValueError(f"Unsafe identifier: {identifier!r}")
    for ch in identifier:
        if not (ch.isalnum() or ch == "_"):
            raise ValueError(f"Unsafe identifier: {identifier!r}")


def _grant_runtime_privileges(engine: Engine, database_url_app: str) -> None:
    app_user = _parse_username(database_url_app)
    if not app_user:
        return
    _assert_safe_pg_identifier(app_user)

    with engine.begin() as conn:
        conn.execute(text(f'GRANT USAGE ON SCHEMA fraud_gov TO "{app_user}"'))
        conn.execute(
            text(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fraud_gov TO "{app_user}"'
            )
        )
        conn.execute(
            text(
                f'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA fraud_gov TO "{app_user}"'
            )
        )


def _bootstrap_schema(engine: Engine) -> None:
    """Ensure the fraud_gov schema matches current ORM models.

    This drops and recreates tables in the fraud_gov schema so tests don't
    depend on a manually-migrated database.
    """

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS fraud_gov"))

        # Drop tables first (reverse dependency order)
        for table in reversed(Base.metadata.sorted_tables):
            schema = table.schema or "fraud_gov"
            conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table.name}" CASCADE'))

        # Drop enums used by the ORM models (best-effort; no-op if absent).
        # These type names come from Enum(..., name=...) in app/db/models.py.
        for type_name in (
            "rule_type",
            "entity_status",
            "approval_status",
            "approval_entity_type",
            "approval_action",
            "audit_entity_type",
            "data_type",
        ):
            conn.execute(text(f'DROP TYPE IF EXISTS fraud_gov."{type_name}" CASCADE'))

        Base.metadata.create_all(bind=conn)


def _assert_schema_current(engine: Engine) -> None:
    """Fail fast with a helpful message if schema is outdated."""
    with engine.connect() as conn:
        # Check for new schema: rulesets should have environment, region, country (NOT activated_at)
        # ruleset_versions should have version, status, activated_at
        result = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='fraud_gov'
                  AND table_name='rulesets'
                  AND column_name='environment'
                """
            )
        ).first()
        if result is None:
            raise RuntimeError(
                "Test database schema is out of date: fraud_gov.rulesets.environment is missing.\n\n"
                "Fix options:\n"
                "- Point DATABASE_URL_APP to a dedicated test DB (name contains 'test' or 'pytest'), then rerun pytest\n"
                "- OR set PYTEST_RESET_DB=1 to allow pytest to drop/recreate the fraud_gov schema automatically\n"
                "- OR run 'uv run local-full-setup --yes' to recreate the local database\n"
            )

        # Also verify ruleset_versions table exists
        result = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='fraud_gov'
                  AND table_name='ruleset_versions'
                  AND column_name='version'
                """
            )
        ).first()
        if result is None:
            raise RuntimeError(
                "Test database schema is out of date: fraud_gov.ruleset_versions.version is missing.\n\n"
                "Fix options:\n"
                "- Point DATABASE_URL_APP to a dedicated test DB (name contains 'test' or 'pytest'), then rerun pytest\n"
                "- OR set PYTEST_RESET_DB=1 to allow pytest to drop/recreate the fraud_gov schema automatically\n"
                "- OR run 'uv run local-full-setup --yes' to recreate the local database\n"
            )


# =============================================================================
# AnyIO Backend Configuration
# =============================================================================
# Per AnyIO testing docs: https://anyio.readthedocs.io/en/stable/testing.html
# This fixture ensures async fixtures work with AnyIO's pytest plugin.
# pytest-asyncio is in strict mode (no asyncio_mode = "auto") to avoid conflicts.
@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def _clean_test_database(test_engine: Engine) -> None:
    """
    Clean all data from test database before the test session.

    This ensures tests start with a clean slate regardless of what data
    may have been left from previous test runs.
    """
    # Only clean if we're not doing a full schema reset
    if _pytest_reset_db_enabled():
        yield
        return

    # Use admin connection if available for TRUNCATE privileges
    database_url_admin = os.environ.get("DATABASE_URL_ADMIN")
    if database_url_admin:
        clean_engine = create_engine(
            _normalize_db_url_for_psycopg(database_url_admin), echo=False, pool_pre_ping=True
        )
    else:
        clean_engine = test_engine

    # Truncate all tables to ensure clean state
    try:
        with clean_engine.begin() as conn:
            conn.execute(text("SET search_path TO fraud_gov, public"))
            # Truncate in reverse dependency order
            for table in reversed(Base.metadata.sorted_tables):
                schema = table.schema or "fraud_gov"
                conn.execute(text(f'TRUNCATE TABLE "{schema}"."{table.name}" CASCADE'))
    except Exception:
        # If truncate fails (e.g., due to permissions), try DELETE instead
        with test_engine.begin() as conn:
            conn.execute(text("SET search_path TO fraud_gov, public"))
            # Delete in reverse dependency order
            for table in reversed(Base.metadata.sorted_tables):
                schema = table.schema or "fraud_gov"
                try:
                    conn.execute(text(f'DELETE FROM "{schema}"."{table.name}"'))
                except Exception:
                    pass  # Skip tables that can't be deleted
    yield


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine]:
    """
    Create a PostgreSQL engine for testing using DATABASE_URL_APP.

    Tests use REAL Postgres (not SQLite) to catch production bugs.
    Automatically converts postgresql:// to postgresql+psycopg:// for psycopg v3.
    """
    database_url_app = _normalize_db_url_for_psycopg(os.environ["DATABASE_URL_APP"])
    engine = create_engine(database_url_app, echo=False, pool_pre_ping=True)

    # Verify connection works
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Postgres: {e}")

    # Ensure the database schema matches the current ORM.
    # IMPORTANT: destructive resets are opt-in via PYTEST_RESET_DB=1.
    if _pytest_reset_db_enabled():
        if not _is_safe_to_reset_database(database_url_app):
            raise RuntimeError(
                "PYTEST_RESET_DB=1 is set but the database name does not look like a dedicated test DB.\n"
                "Refusing to drop/recreate schema. Use a DB name containing 'test' or 'pytest'."
            )

        database_url_admin = os.environ.get("DATABASE_URL_ADMIN")
        ddl_engine = engine
        used_admin = False
        if database_url_admin:
            ddl_engine = create_engine(
                _normalize_db_url_for_psycopg(database_url_admin), echo=False, pool_pre_ping=True
            )
            used_admin = True

        _bootstrap_schema(ddl_engine)
        if used_admin:
            _grant_runtime_privileges(ddl_engine, database_url_app)
    else:
        _assert_schema_current(engine)

    yield engine

    # Note: Don't drop tables - tests use transaction rollback for isolation


@pytest.fixture(scope="function")
def db_session(test_engine: Engine) -> Generator[Session]:
    """
    Provide a clean database session for each test function.

    Automatically rolls back changes after each test to ensure isolation.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    connection.execute(text("SET search_path TO fraud_gov, public"))

    session_factory = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = session_factory()

    # Most API endpoints call db.commit(). In tests we want isolation via a single
    # outer transaction, so we turn commit() into flush(). For flows that require
    # real commits, use the clean_db_session fixture.
    session.commit = session.flush  # type: ignore[method-assign]

    yield session

    # Rollback and cleanup
    session.rollback()
    # Guard transaction.rollback() because in some situations the connection
    # may already have been deassociated which raises an SAWarning. Only
    # attempt to rollback if the transaction is still active.
    try:
        if getattr(transaction, "is_active", True):
            transaction.rollback()
    except Exception:
        # Best-effort: ignore errors during rollback to avoid noisy warnings
        pass

    session.close()
    connection.close()


@pytest.fixture(scope="function")
def clean_db_session(test_engine: Engine) -> Generator[Session]:
    """
    Provide a database session that commits changes (for complex test flows).

    Tables are truncated after the test to ensure clean state.
    """
    connection = test_engine.connect()
    # Ensure any connection-level setup runs within a predictable transaction
    # scope to avoid SQLAlchemy 2.x autobegin conflicts.
    connection.execute(text("SET search_path TO fraud_gov, public"))
    session_factory = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = session_factory()

    yield session

    # Clean up all test data from Postgres tables
    session.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        schema = table.schema or "fraud_gov"
        session.execute(text(f'DELETE FROM "{schema}"."{table.name}"'))
    session.commit()

    session.close()
    connection.close()


# ============================================================================
# Async SQLAlchemy Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
async def reset_async_engine_before_test():
    """Reset async database engine before each test for fresh connections.

    This ensures that asyncpg connections are not reused across different
    event loops, which causes 'Future attached to a different loop' errors.
    """
    from app.core.db import reset_async_engine

    await reset_async_engine()
    yield


@pytest.fixture(scope="function")
async def async_engine() -> AsyncGenerator[AsyncEngine]:
    """
    Create a fresh async PostgreSQL engine for testing.

    Uses create_fresh_async_engine() to avoid singleton caching,
    ensuring the engine is bound to the current event loop.
    """
    from app.core.db import create_fresh_async_engine

    engine = create_fresh_async_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield engine
    await engine.dispose()


@pytest.fixture(scope="function")
async def async_db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """
    Provide a clean async database session for each test function.

    Automatically rolls back changes after each test to ensure isolation.
    Uses transaction-level isolation with nested async transactions.
    """

    # Create connection and start transaction
    async with async_engine.connect() as connection:
        # Start a transaction at connection level
        transaction = await connection.begin()
        await connection.execute(text("SET search_path TO fraud_gov, public"))

        # Create session bound to this connection
        session_maker = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
        )
        session = session_maker()

        # Patch commit() to flush() for test isolation
        session.commit = lambda: session.flush()  # type: ignore[method-assign]

        try:
            yield session
        finally:
            # Rollback and cleanup
            await session.rollback()
            await session.close()
            # Rollback the transaction
            if transaction.is_active:
                await transaction.rollback()


@pytest.fixture(scope="function")
async def clean_async_db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """
    Provide an async database session that commits changes.

    Uses a FRESH connection (dispose old ones) to ensure isolation from
    previous tests that may have committed data. Tables are truncated
    BEFORE and AFTER the test to ensure clean state.

    Use this for complex test flows requiring real commits.
    """
    import logging

    logger = logging.getLogger(__name__)

    # Dispose any existing pooled connections to ensure fresh connection
    await async_engine.dispose()

    async with async_engine.connect() as connection:
        await connection.execute(text("SET search_path TO fraud_gov, public"))

        # Truncate ALL tables BEFORE the test to ensure clean state
        # This handles cases where previous tests committed data
        for table in Base.metadata.sorted_tables:
            schema = table.schema or "fraud_gov"
            try:
                await connection.execute(text(f'TRUNCATE TABLE "{schema}"."{table.name}" CASCADE'))
            except Exception as e:
                logger.warning(f"Failed to truncate {schema}.{table.name}: {e}")

        try:
            await connection.commit()
        except Exception as e:
            logger.warning(f"Failed to commit truncation: {e}")
            await connection.rollback()

        session_maker = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
        )
        session = session_maker()

        try:
            yield session
        finally:
            # Clean up all test data AFTER the test
            await session.rollback()
            for table in reversed(Base.metadata.sorted_tables):
                schema = table.schema or "fraud_gov"
                await session.execute(text(f'DELETE FROM "{schema}"."{table.name}"'))
            await session.commit()
            await session.close()


# ============================================================================
# Mock Authentication Fixtures
# ============================================================================


def create_mock_token(sub: str = "test-user", roles: list[str] | None = None) -> dict[str, Any]:
    """
    Create a mock JWT token payload for testing.

    Args:
        sub: User subject/ID (e.g., "auth0|123456")
        roles: List of roles (e.g., ["PLATFORM_ADMIN", "RULE_MAKER"])

    Returns:
        Mock JWT payload dictionary with both roles and permissions claims
    """
    if roles is None:
        roles = []

    # Permission mapping for roles (matches require_role() in security.py)
    role_permissions = {
        "PLATFORM_ADMIN": {
            # Rule Management
            "rule:create",
            "rule:update",
            "rule:submit",
            "rule:approve",
            "rule:reject",
            "rule:read",
            # RuleField Management
            "rule_field:create",
            "rule_field:update",
            "rule_field:delete",
            "rule_field:read",
            # RuleSet Management
            "ruleset:create",
            "ruleset:update",
            "ruleset:submit",
            "ruleset:approve",
            "ruleset:reject",
            "ruleset:activate",
            "ruleset:compile",
            "ruleset:read",
        },
        "RULE_MAKER": {
            "rule:create",
            "rule:update",
            "rule:submit",
            "rule:read",
            "ruleset:create",
            "ruleset:update",
            "ruleset:submit",
            "ruleset:compile",
            "ruleset:read",
        },
        "RULE_CHECKER": {
            "rule:approve",
            "rule:reject",
            "rule:read",
            "ruleset:approve",
            "ruleset:reject",
            "ruleset:read",
        },
        "RULE_VIEWER": {"rule:read", "ruleset:read"},
        "FRAUD_ANALYST": {"rule:read", "ruleset:read"},
        "FRAUD_SUPERVISOR": {"rule:read", "ruleset:read"},
    }

    # Collect all permissions for the given roles
    permissions = set()
    for role in roles:
        permissions.update(role_permissions.get(role, set()))

    return {
        "sub": sub,
        f"{os.environ['AUTH0_AUDIENCE']}/roles": roles,
        "permissions": list(permissions),  # New permission-based auth
        "aud": os.environ["AUTH0_AUDIENCE"],
        "iss": f"https://{os.environ['AUTH0_DOMAIN']}/",
        "exp": 9999999999,  # Far future expiration
    }


@pytest.fixture
def mock_user() -> dict[str, Any]:
    """Mock authenticated user with no specific roles."""
    return create_mock_token(sub="user-123", roles=[])


@pytest.fixture
def mock_admin() -> dict[str, Any]:
    """Mock authenticated user with PLATFORM_ADMIN role."""
    return create_mock_token(sub="admin-123", roles=["PLATFORM_ADMIN"])


@pytest.fixture
def mock_maker() -> dict[str, Any]:
    """Mock authenticated user with RULE_MAKER role."""
    return create_mock_token(sub="maker-123", roles=["RULE_MAKER"])


@pytest.fixture
def mock_checker() -> dict[str, Any]:
    """Mock authenticated user with RULE_CHECKER role."""
    return create_mock_token(sub="checker-123", roles=["RULE_CHECKER"])


@pytest.fixture
def mock_maker_checker() -> dict[str, Any]:
    """Mock authenticated user with both RULE_MAKER and RULE_CHECKER roles."""
    return create_mock_token(sub="maker-checker-123", roles=["RULE_MAKER", "RULE_CHECKER"])


# ============================================================================
# FastAPI TestClient Fixtures
# ============================================================================


def _create_test_client(
    db_session: Session | None = None,
    async_db_session: AsyncSession | None = None,
    mock_user: dict[str, Any] | None = None,
) -> TestClient:
    """
    Factory function to create TestClient with optional auth.

    Args:
        db_session: Sync database session to inject (deprecated, use async_db_session)
        async_db_session: Async database session to inject (preferred)
        mock_user: Optional mock user payload for authentication

    Returns:
        Configured TestClient instance
    """
    from app.core.dependencies import get_async_db_session

    app = create_app()

    # Always override database - prefer async if available
    if async_db_session is not None:
        # IMPORTANT: For TestClient (sync), we must use a synchronous override.
        # Using an async generator here causes greenlet errors.
        # The session should already be properly scoped and managed.

        def override_get_async_db():
            yield async_db_session

        app.dependency_overrides[get_async_db_session] = override_get_async_db
    elif db_session is not None:

        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db_session] = override_get_db

    # Optionally override authentication
    if mock_user is not None:

        async def override_get_current_user():
            return mock_user

        app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app)


@pytest.fixture
async def client(async_db_session: AsyncSession):
    """AsyncClient without authentication."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def authenticated_client(async_db_session: AsyncSession, mock_user: dict):
    """AsyncClient with basic authenticated user (no specific roles)."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_client(async_db_session: AsyncSession, mock_admin: dict):
    """AsyncClient with ADMIN role."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_admin

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def maker_client(async_db_session: AsyncSession, mock_maker: dict):
    """AsyncClient with MAKER role."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_maker

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def checker_client(async_db_session: AsyncSession, mock_checker: dict):
    """AsyncClient with CHECKER role."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_checker

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# Async client fixtures for tests that need async session injection
@pytest.fixture
async def async_client(async_db_session: AsyncSession):
    """AsyncClient without authentication, using async session."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def async_admin_client(async_db_session: AsyncSession, mock_admin: dict):
    """AsyncClient with ADMIN role, using async session."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_admin

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def async_authenticated_client(async_db_session: AsyncSession, mock_user: dict):
    """AsyncClient with authenticated user (no specific role), using async session."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def async_maker_client(async_db_session: AsyncSession, mock_maker: dict):
    """AsyncClient with MAKER role, using async session."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_maker

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def async_checker_client(async_db_session: AsyncSession, mock_checker: dict):
    """AsyncClient with CHECKER role, using async session."""
    import httpx

    from app.core.dependencies import get_async_db_session

    app = create_app()

    def override_get_async_db():
        yield async_db_session

    app.dependency_overrides[get_async_db_session] = override_get_async_db

    async def override_get_current_user():
        return mock_checker

    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def app(db_session: Session):
    """Provide the FastAPI application instance with DB dependency overridden for tests."""
    app = create_app()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db
    return app


# ============================================================================
# Test Data Factories
# ============================================================================


@pytest.fixture
def sample_rule_field_data() -> dict[str, Any]:
    """Sample data for creating a RuleField."""
    return {
        "field_key": "transaction_amount",
        "field_id": 27,
        "display_name": "Transaction Amount",
        "description": "Transaction amount in cents",
        "data_type": "NUMBER",
        "allowed_operators": ["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"],
        "multi_value_allowed": False,
        "is_sensitive": False,
        "current_version": 1,
        "version": 1,
        "created_by": "test@example.com",
    }


@pytest.fixture
def sample_condition_tree() -> dict[str, Any]:
    """Sample condition tree for rule creation."""
    return {
        "type": "CONDITION",
        "field": "transaction_amount",
        "operator": "GT",
        "value": 1000,
    }


@pytest.fixture
def sample_rule_data(sample_condition_tree: dict) -> dict[str, Any]:
    """Sample data for creating a Rule."""
    return {
        "rule_name": "High Value Transaction",
        "description": "Flag transactions above $1000",
        "rule_type": "ALLOWLIST",
        "condition_tree": sample_condition_tree,
        "priority": 100,
    }


@pytest.fixture
def sample_ruleset_data() -> dict[str, Any]:
    """Sample data for creating a RuleSet."""
    return {
        "environment": "local",
        "region": "INDIA",
        "country": "IN",
        "rule_type": "ALLOWLIST",
        "name": "US Fraud Rules v1",
        "description": "Fraud detection rules for US region",
    }


# ============================================================================
# Database Helper Functions
# ============================================================================


async def create_rule_field_in_db(session: AsyncSession, **kwargs) -> Any:
    """
    Helper to create a RuleField directly in the database.

    Uses real Postgres with native ARRAY type (not SQLite JSON).

    If a field with the same field_key already exists (e.g., from seed data),
    returns the existing field instead of creating a duplicate.
    """
    # Get next field_id if not provided
    from sqlalchemy import func

    from app.db.models import RuleField

    max_id = await session.execute(session.query(func.max(RuleField.field_id)))
    next_id = (max_id.scalar_one_or_none() or 26) + 1

    defaults = {
        "field_key": f"test_field_{uuid.uuid7().hex[:8]}",
        "field_id": kwargs.get("field_id", next_id),
        "display_name": "Test Field",
        "description": None,
        "data_type": "STRING",
        "allowed_operators": ["EQ"],  # Postgres TEXT[] array
        "multi_value_allowed": False,
        "is_sensitive": False,
        "current_version": 1,
        "version": 1,
        "created_by": "test@example.com",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)

    field_key = defaults["field_key"]

    # Check if field already exists (from seed data or previous test)
    existing = await session.execute(
        session.query(RuleField).filter_by(field_key=field_key).statement
    )
    existing = existing.scalar_one_or_none()

    if existing:
        await session.refresh(existing)
        return existing

    field = RuleField(**defaults)
    session.add(field)
    await session.commit()
    await session.refresh(field)
    return field


async def create_rule_in_db(session: AsyncSession, created_by: str = "test-user", **kwargs) -> Any:
    """Helper to create a Rule with initial version in the database."""
    from app.db.models import Rule, RuleVersion
    from app.domain.enums import EntityStatus, RuleType

    rule_id = kwargs.get("rule_id", uuid.uuid7())

    # Create Rule
    rule_defaults = {
        "rule_id": rule_id,
        "rule_name": "Test Rule",
        "description": "Test Description",
        "rule_type": RuleType.ALLOWLIST.value,
        "current_version": 1,
        "status": EntityStatus.DRAFT.value,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Extract Rule-specific kwargs
    for key in ["rule_name", "description", "rule_type", "status"]:
        if key in kwargs:
            rule_defaults[key] = kwargs.pop(key)

    rule = Rule(**rule_defaults)
    session.add(rule)

    # Create initial RuleVersion
    # Determine action based on rule_type
    rule_type_for_action = rule_defaults.get("rule_type", RuleType.ALLOWLIST.value)
    action_map = {
        RuleType.ALLOWLIST.value: "APPROVE",
        RuleType.BLOCKLIST.value: "DECLINE",
        RuleType.AUTH.value: "APPROVE",
        RuleType.MONITORING.value: "REVIEW",
    }
    default_action = action_map.get(rule_type_for_action, "REVIEW")

    version_defaults = {
        "rule_version_id": uuid.uuid7(),
        "rule_id": rule_id,
        "version": 1,
        "condition_tree": {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
        "priority": 100,
        "action": default_action,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "status": EntityStatus.DRAFT.value,
    }

    # Apply custom overrides
    for key in ["condition_tree", "priority", "version_status", "action"]:
        if key in kwargs:
            if key == "version_status":
                version_defaults["status"] = kwargs[key]
            else:
                version_defaults[key] = kwargs[key]

    rule_version = RuleVersion(**version_defaults)
    session.add(rule_version)

    await session.commit()
    await session.refresh(rule)
    return rule


async def create_ruleset_in_db(
    session: AsyncSession, created_by: str = "test-user", **kwargs
) -> Any:
    """Helper to create a RuleSet identity with initial version in the database.

    Uses the new schema where RuleSet is identity-only and RuleSetVersion
    contains the version and status.
    """
    from app.db.models import RuleSet, RuleSetVersion
    from app.domain.enums import EntityStatus

    ruleset_id = kwargs.get("ruleset_id", uuid.uuid7())

    # Create RuleSet identity
    ruleset_defaults = {
        "ruleset_id": ruleset_id,
        "environment": kwargs.get("environment", "local"),
        "region": kwargs.get("region", "INDIA"),
        "country": kwargs.get("country", "IN"),
        "rule_type": kwargs.get("rule_type", "ALLOWLIST"),
        "name": kwargs.get("name", "Test Ruleset"),
        "description": kwargs.get("description", None),
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    ruleset = RuleSet(**ruleset_defaults)
    session.add(ruleset)

    # Create initial RuleSetVersion
    version_defaults = {
        "ruleset_version_id": uuid.uuid7(),
        "ruleset_id": ruleset_id,
        "version": 1,
        "status": kwargs.get("status", EntityStatus.DRAFT.value),
        "created_by": created_by,
        "created_at": datetime.now(UTC),
    }

    ruleset_version = RuleSetVersion(**version_defaults)
    session.add(ruleset_version)

    await session.commit()
    await session.refresh(ruleset)
    await session.refresh(ruleset_version)
    return {"ruleset": ruleset, "version": ruleset_version}


# ============================================================================
# Async Database Helper Functions
# ============================================================================


async def acreate_rule_field_in_db(session: AsyncSession, **kwargs) -> Any:
    """
    Async helper to create a RuleField directly in the database.

    If a field with the same field_key already exists, returns the existing field.
    """
    from sqlalchemy import func, select

    from app.db.models import RuleField

    # Get next field_id if not provided
    max_id_result = await session.execute(select(func.max(RuleField.field_id)))
    max_id = max_id_result.scalar_one_or_none()
    next_id = (max_id or 26) + 1

    defaults = {
        "field_key": f"test_field_{uuid.uuid7().hex[:8]}",
        "field_id": kwargs.get("field_id", next_id),
        "display_name": "Test Field",
        "description": None,
        "data_type": "STRING",
        "allowed_operators": ["EQ"],
        "multi_value_allowed": False,
        "is_sensitive": False,
        "current_version": 1,
        "version": 1,
        "created_by": "test@example.com",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)

    field_key = defaults["field_key"]

    # Check if field already exists
    existing_result = await session.execute(
        select(RuleField).where(RuleField.field_key == field_key)
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        await session.refresh(existing)
        return existing

    field = RuleField(**defaults)
    session.add(field)
    await session.commit()
    await session.refresh(field)
    return field


async def acreate_rule_in_db(session: AsyncSession, created_by: str = "test-user", **kwargs) -> Any:
    """Async helper to create a Rule with initial version in the database."""
    from app.db.models import Rule, RuleVersion
    from app.domain.enums import EntityStatus, RuleType

    rule_id = kwargs.get("rule_id", uuid.uuid7())

    # Create Rule
    rule_defaults = {
        "rule_id": rule_id,
        "rule_name": "Test Rule",
        "description": "Test Description",
        "rule_type": RuleType.ALLOWLIST.value,
        "current_version": 1,
        "status": EntityStatus.DRAFT.value,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Extract Rule-specific kwargs
    for key in ["rule_name", "description", "rule_type", "status"]:
        if key in kwargs:
            rule_defaults[key] = kwargs.pop(key)

    rule = Rule(**rule_defaults)
    session.add(rule)

    # Create initial RuleVersion
    rule_type_for_action = rule_defaults.get("rule_type", RuleType.ALLOWLIST.value)
    action_map = {
        RuleType.ALLOWLIST.value: "APPROVE",
        RuleType.BLOCKLIST.value: "DECLINE",
        RuleType.AUTH.value: "APPROVE",
        RuleType.MONITORING.value: "REVIEW",
    }
    default_action = action_map.get(rule_type_for_action, "REVIEW")

    version_defaults = {
        "rule_version_id": uuid.uuid7(),
        "rule_id": rule_id,
        "version": 1,
        "condition_tree": {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
        "priority": 100,
        "action": default_action,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "status": EntityStatus.DRAFT.value,
    }

    # Apply custom overrides
    for key in ["condition_tree", "priority", "version_status", "action"]:
        if key in kwargs:
            if key == "version_status":
                version_defaults["status"] = kwargs[key]
            else:
                version_defaults[key] = kwargs[key]

    rule_version = RuleVersion(**version_defaults)
    session.add(rule_version)

    await session.commit()
    await session.refresh(rule)
    return rule


async def acreate_ruleset_in_db(
    session: AsyncSession, created_by: str = "test-user", **kwargs
) -> Any:
    """Async helper to create a RuleSet identity with initial version."""
    from app.db.models import RuleSet, RuleSetVersion
    from app.domain.enums import EntityStatus

    ruleset_id = kwargs.get("ruleset_id", uuid.uuid7())

    # Create RuleSet identity
    ruleset_defaults = {
        "ruleset_id": ruleset_id,
        "environment": kwargs.get("environment", "local"),
        "region": kwargs.get("region", "INDIA"),
        "country": kwargs.get("country", "IN"),
        "rule_type": kwargs.get("rule_type", "ALLOWLIST"),
        "name": kwargs.get("name", "Test Ruleset"),
        "description": kwargs.get("description", None),
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    ruleset = RuleSet(**ruleset_defaults)
    session.add(ruleset)

    # Create initial RuleSetVersion
    version_defaults = {
        "ruleset_version_id": uuid.uuid7(),
        "ruleset_id": ruleset_id,
        "version": 1,
        "status": kwargs.get("status", EntityStatus.DRAFT.value),
        "created_by": created_by,
        "created_at": datetime.now(UTC),
    }

    ruleset_version = RuleSetVersion(**version_defaults)
    session.add(ruleset_version)

    await session.commit()
    await session.refresh(ruleset)
    await session.refresh(ruleset_version)
    return {"ruleset": ruleset, "version": ruleset_version}


@pytest.fixture
def db_rule_field(db_session: Session, sample_rule_field_data: dict) -> Any:
    """Create a RuleField in the test database."""
    return create_rule_field_in_db(db_session, **sample_rule_field_data)


@pytest.fixture
def db_rule(db_session: Session) -> Any:
    """Create a Rule with initial version in the test database."""
    return create_rule_in_db(db_session)


# ============================================================================
# Async Database Fixtures (using async helper functions)
# ============================================================================


@pytest.fixture
async def adb_rule_field(async_db_session: AsyncSession, sample_rule_field_data: dict) -> Any:
    """Create a RuleField in the test database using async session."""
    return await acreate_rule_field_in_db(async_db_session, **sample_rule_field_data)


@pytest.fixture
async def adb_rule(async_db_session: AsyncSession) -> Any:
    """Create a Rule with initial version using async session."""
    return await acreate_rule_in_db(async_db_session)


@pytest.fixture
async def adb_ruleset(async_db_session: AsyncSession) -> Any:
    """Create a RuleSet with initial version using async session."""
    return await acreate_ruleset_in_db(async_db_session)


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """
    Reset the in-memory rate limiter before each test.

    This ensures tests don't fail due to rate limits from previous tests.
    """
    from app.core.rate_limit import get_rate_limiter

    limiter = get_rate_limiter()
    limiter.reset()
    yield


# ============================================================================
# E2E Test Server Management (for real HTTP integration tests)
# ============================================================================


def _wait_for_e2e_server(base_url: str, timeout_s: int) -> None:
    import time

    start_time = time.time()
    while time.time() - start_time < timeout_s:
        try:
            response = httpx.get(f"{base_url}/api/v1/health", timeout=1.0)
            if response.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"E2E server failed to become healthy within {timeout_s}s: {base_url}")


def _kill_process_on_port_windows(port: int) -> None:
    import subprocess
    import time

    try:
        result = subprocess.run(
            [
                "powershell",
                "-Command",
                (
                    f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue "
                    "| Select-Object -ExpandProperty OwningProcess"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pid = result.stdout.strip()
        if pid:
            print(f"\nKilling existing process {pid} on port {port}...")
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            time.sleep(1)
    except Exception:
        # Best-effort only.
        pass


@pytest.fixture(scope="session")
def e2e_server_port() -> int:
    """Port for E2E test server. Override with E2E_PORT env var."""
    return int(os.environ.get("E2E_PORT", "8001"))


@pytest.fixture(scope="session")
def e2e_server_base_url(e2e_server_port: int) -> Generator[str]:
    """
    Start a real uvicorn server for E2E tests.

    This fixture:
    - Kills any existing process on the port (prevents port locks)
    - Starts uvicorn in a subprocess at the session scope
    - Waits for /api/v1/health to return 200
    - Yields the base URL for tests
    - Ensures server is terminated after all tests complete

    Usage:
        def test_e2e_health(e2e_server_base_url: str):
            response = httpx.get(f"{e2e_server_base_url}/api/v1/health")
            assert response.status_code == 200
    """
    import subprocess
    import sys

    port = e2e_server_port
    base_url = f"http://127.0.0.1:{port}"

    use_existing = os.environ.get("E2E_USE_EXISTING_SERVER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    if use_existing:
        # Don't kill or spawn anything; just wait for the server to be ready.
        _wait_for_e2e_server(base_url, timeout_s=30)
        yield base_url
        return

    # Kill any existing process on the port (Windows only)
    if sys.platform == "win32":
        _kill_process_on_port_windows(port)

    # Start uvicorn server
    print(f"\nStarting E2E test server on {base_url}...")
    server_proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        # Avoid PIPE to prevent deadlocks if the child is chatty.
        stdout=None,
        stderr=None,
        text=True,
    )

    try:
        _wait_for_e2e_server(base_url, timeout_s=30)
    except Exception:
        # Kill server on failure
        try:
            server_proc.kill()
            server_proc.wait(timeout=5)
        except Exception:
            pass
        raise

    print(f"E2E test server ready at {base_url}")

    try:
        yield base_url
    finally:
        # Cleanup: ALWAYS terminate server, even if tests fail
        print("\nStopping E2E test server...")
        try:
            server_proc.terminate()
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Force killing E2E server...")
            server_proc.kill()
            server_proc.wait(timeout=5)
        except Exception as e:
            print(f"Error stopping server: {e}")
        else:
            print("E2E test server stopped")
