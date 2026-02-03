import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.db import get_async_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def verify_health_token(x_health_token: Annotated[str | None, Header()] = None) -> None:
    """
    Verify health check token if configured.

    This is an optional security feature. When HEALTH_TOKEN is set, health endpoints
    require authentication. This prevents reconnaissance attacks while still allowing
    Kubernetes liveness/readiness probes when the token is shared with the cluster.

    If HEALTH_TOKEN is not set, health endpoints remain public (standard K8s behavior).
    """
    expected_token = settings.health_token
    if expected_token:
        import hmac

        if not x_health_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Health token required",
            )
        if not hmac.compare_digest(x_health_token, expected_token):
            logger.warning(
                "Unauthorized health check attempt",
                extra={
                    "security_event": True,
                    "event_type": "HEALTH_ACCESS_DENIED",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid health token",
            )


def get_health_dependencies():
    """Get health endpoint dependencies based on configuration."""
    if settings.health_token:
        return [Depends(verify_health_token)]
    return []


@router.get("/health", dependencies=get_health_dependencies())
def health() -> dict:
    """Basic health check endpoint (public unless HEALTH_TOKEN is set)."""
    return {"ok": True}


@router.get("/readyz", dependencies=get_health_dependencies())
async def readyz() -> JSONResponse:
    """Readiness probe: verifies database connectivity.

    Returns:
      - 200 when DB is reachable
      - 503 when DB is unavailable

    Note: Public unless HEALTH_TOKEN is set. For production, consider setting
    HEALTH_TOKEN to prevent reconnaissance of database availability.
    """
    try:
        engine: AsyncEngine = get_async_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True, "db": "ok"})
    except Exception as exc:
        logger.error(f"Health check failed: {exc}", exc_info=True)
        # Don't expose internal error details to callers
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ok": False, "db": "unavailable"},
        )
