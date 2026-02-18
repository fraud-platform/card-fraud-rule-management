"""Monitoring and metrics endpoints.

Provides Prometheus metrics endpoint for observability.
The metrics endpoint is protected by a token for security.
"""

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from app.core.config import settings
from app.core.observability import metrics_endpoint

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Monitoring"])


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    """Prometheus metrics endpoint for scraping.

    SECURITY: Requires X-Metrics-Token header for authentication.
    Exposes internal system metrics that could aid reconnaissance if leaked.

    Args:
        request: The incoming request with X-Metrics-Token header

    Returns:
        Prometheus metrics in text format

    Raises:
        HTTPException: If token is missing or invalid
    """
    # Verify token is configured
    expected_token = settings.metrics_token
    if not expected_token:
        logger.error(
            "Metrics endpoint accessed but METRICS_TOKEN not configured",
            extra={"security_event": True, "event_type": "METRICS_NOT_CONFIGURED"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Metrics token not configured. Set METRICS_TOKEN environment variable.",
        )

    # Verify token using constant-time comparison to prevent timing attacks
    metrics_token = request.headers.get("X-Metrics-Token")
    if not hmac.compare_digest(metrics_token or "", expected_token):
        logger.warning(
            "Unauthorized metrics access attempt",
            extra={
                "security_event": True,
                "event_type": "METRICS_ACCESS_DENIED",
                "client_ip": request.client.host if request.client else "unknown",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid metrics token",
        )

    return metrics_endpoint()
