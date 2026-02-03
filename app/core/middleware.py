"""Security middleware for FastAPI application."""

import logging
from collections.abc import Callable

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size.

    Prevents DoS attacks by rejecting overly large requests.

    SECURITY: Validates both Content-Length header AND actual body size
    to prevent bypass via missing/falsified headers.
    """

    def __init__(self, app, max_size_mb: int = 1):
        """
        Initialize middleware with max request size.

        Args:
            app: FastAPI application
            max_size_mb: Maximum request size in megabytes (default: 1MB)
        """
        super().__init__(app)
        self.max_size_bytes = max_size_mb * 1024 * 1024

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and enforce size limit.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response or 413 error if request too large
        """
        # First check: content-length header if present (fast rejection)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.max_size_bytes:
                    logger.warning(
                        f"Request size {size} bytes (from header) exceeds limit "
                        f"{self.max_size_bytes} bytes",
                        extra={"path": request.url.path, "client": request.client},
                    )
                    return Response(
                        content='{"error":"RequestTooLarge","message":"Request body exceeds maximum allowed size"}',
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        media_type="application/json",
                    )
            except ValueError:
                # Invalid content-length header - will verify actual body size below
                pass

        # Second check: for POST/PUT/PATCH requests, verify actual body size
        # This prevents bypass via missing or falsified Content-Length header
        if request.method in ("POST", "PUT", "PATCH"):
            # Read the body to verify actual size
            # Note: This consumes the body, so we need to replace it in the request
            body = await request.body()
            actual_size = len(body)

            if actual_size > self.max_size_bytes:
                logger.warning(
                    f"Request size {actual_size} bytes (actual) exceeds limit "
                    f"{self.max_size_bytes} bytes",
                    extra={"path": request.url.path, "client": request.client},
                )
                return Response(
                    content='{"error":"RequestTooLarge","message":"Request body exceeds maximum allowed size"}',
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    media_type="application/json",
                )

            # Create a new request with the body for downstream handlers
            async def receive():
                return {"type": "http.request", "body": body}

            request._receive = receive

        response = await call_next(request)
        return response
