"""
FastAPI dependency injection utilities.

Provides reusable dependencies for database sessions, authentication,
and other cross-cutting concerns.

NOTE: This module uses permission-based authorization via require_permission()
from app.core.security. The old role-based dependencies (RequireMaker, RequireChecker,
RequireAdmin) have been removed from production code. Use require_permission() directly
in your endpoints.

The legacy dependency functions below are provided for TEST COMPATIBILITY ONLY and should
not be used in new code.
"""

import warnings
from collections.abc import AsyncGenerator, Generator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.db import get_async_sessionmaker, get_db_session
from app.core.security import get_current_user as _get_current_user

# ============================================================================
# Database Dependencies
# ============================================================================

# Type alias for sync database session dependency (DEPRECATED)
DbSession = Annotated[Session, Depends(get_db_session)]


async def get_async_db_session() -> AsyncGenerator[AsyncSession]:
    """
    Async database session dependency for FastAPI endpoints.

    This is the preferred way to get database sessions in new code.

    Usage:
        @router.get("/rules")
        async def list_rules(db: AsyncDbSession):
            result = await db.execute(select(Rule))
            return result.scalars().all()

    Yields:
        Async SQLAlchemy database session
    """
    session_maker = get_async_sessionmaker()
    async with session_maker() as session:
        yield session


# Type alias for async database session dependency (preferred)
AsyncDbSession = Annotated[AsyncSession, Depends(get_async_db_session)]


def get_db() -> Generator[Session]:
    """
    Database session dependency for FastAPI endpoints (sync, DEPRECATED).

    DEPRECATED: Use async sessions (AsyncDbSession) for new code.
    This is kept for backward compatibility and test support only.

    This is a convenience re-export of get_db_session for cleaner imports.

    Usage:
        @router.get("/rules")
        def list_rules(db: DbSession):
            return db.query(Rule).all()

    Yields:
        SQLAlchemy database session
    """
    warnings.warn(
        "Sync database sessions are deprecated. Use AsyncDbSession instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    yield from get_db_session()


# ============================================================================
# Authentication Dependencies
# ============================================================================


def get_current_user(user: dict[str, Any] = Depends(_get_current_user)) -> dict[str, Any]:
    """
    Re-export of get_current_user from security module.

    Extracts and verifies the current user from the JWT token.
    Use this dependency for endpoints that require authentication
    but no specific permission.

    Usage:
        @router.get("/profile")
        def get_profile(user: CurrentUser):
            return {"user_id": user["sub"]}

    For permission-based authorization, use require_permission() directly:
        from app.core.security import require_permission

        @router.post("/rules")
        def create_rule(
            payload: RuleCreate,
            db: DbSession,
            user: CurrentUser = Depends(require_permission("rule:create")),
        ):
            ...

    Returns:
        Decoded JWT payload containing user information
    """
    return user


# Type alias for authenticated user dependency
CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


# ============================================================================
# Legacy Role Dependencies (TEST COMPATIBILITY ONLY)
# ============================================================================
# NOTE: These are provided for test compatibility only. Use require_permission() in new code.


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Legacy dependency for tests. Use require_permission() in new code."""
    return user


def require_maker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Legacy dependency for tests. Use require_permission() in new code."""
    return user


def require_checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Legacy dependency for tests. Use require_permission() in new code."""
    return user


# Type aliases for legacy dependencies (for test compatibility only)
RequireAdmin = Annotated[dict[str, Any], Depends(require_admin)]
RequireMaker = Annotated[dict[str, Any], Depends(require_maker)]
RequireChecker = Annotated[dict[str, Any], Depends(require_checker)]
