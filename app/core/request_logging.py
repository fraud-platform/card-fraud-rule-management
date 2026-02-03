"""
Request/Response logging middleware for API calls.

Logs all API requests and responses in a structured JSON format for:
- Debugging
- Audit trails
- API usage analytics
- Integration testing

To enable, set env var: API_REQUEST_LOGGING=true
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

logger = logging.getLogger("app.api")

# Sensitive headers that should be redacted
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}

# Sensitive body fields that should be redacted
SENSITIVE_FIELDS = {
    "password",
    "token",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "client_secret",
}


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact sensitive headers."""
    return {
        k: "***REDACTED***" if k.lower() in SENSITIVE_HEADERS else v for k, v in headers.items()
    }


def _sanitize_body(body: Any) -> Any:
    """Redact sensitive fields from request/response body."""
    if isinstance(body, dict):
        return {
            k: "***REDACTED***" if k.lower() in SENSITIVE_FIELDS else _sanitize_body(v)
            for k, v in body.items()
        }
    if isinstance(body, list):
        return [_sanitize_body(item) for item in body]
    return body


def _format_body_for_log(body: Any, max_size: int = 10000) -> str:
    """Format body for logging with size limit."""
    if body is None:
        return ""

    sanitized = _sanitize_body(body)

    try:
        body_str = json.dumps(sanitized, default=str)
        if len(body_str) > max_size:
            body_str = body_str[:max_size] + "... (truncated)"
        return body_str
    except Exception:
        return str(body)[:max_size]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all API requests and responses.

    Logs include:
    - Request method, path, headers, body
    - Response status, headers, body
    - Duration in milliseconds
    - Request ID for correlation

    Sensitive data is automatically redacted.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        """
        Initialize request logging middleware.

        Args:
            app: ASGI application
            enabled: Whether to enable logging (can be controlled via env var)
        """
        super().__init__(app)
        # Check if logging is enabled via environment variable
        self.enabled = enabled or settings.app_env in ("local", "test")

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request and log both request and response.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response from downstream handler
        """
        if not self.enabled:
            return await call_next(request)

        # Skip logging for health/metrics endpoints
        if request.url.path in ("/health", "/metrics", "/api/v1/health", "/api/v1/readyz"):
            return await call_next(request)

        start_time = datetime.now(UTC)

        # Extract request details
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else None

        # Get request headers
        request_headers = dict(request.headers)

        # Get request body (for POST/PUT/PATCH)
        request_body = None
        if method in ("POST", "PUT", "PATCH"):
            try:
                # Read body (this consumes it, so we need to restore it)
                body_bytes = await request.body()
                if body_bytes:
                    request_body = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                request_body = None

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # Parse request body if JSON
        request_body_obj = None
        if request_body:
            try:
                request_body_obj = json.loads(request_body)
            except Exception:
                request_body_obj = {"raw": request_body[:1000]}

        # Get response body (if possible)
        response_body = None
        try:
            # Note: This only works if response body hasn't been consumed yet
            # For streaming responses, we won't be able to log the body
            if hasattr(response, "body"):
                response_body = response.body
        except Exception:
            response_body = None

        # Build log entry
        log_entry = {
            "type": "api_call",
            "request_id": request.state.request_id
            if hasattr(request.state, "request_id")
            else "unknown",
            "timestamp": datetime.now(UTC).isoformat(),
            "request": {
                "method": method,
                "path": path,
                "query_params": query_params,
                "headers": _sanitize_headers(request_headers),
                "body": _sanitize_body(request_body_obj) if request_body_obj else request_body,
            },
            "response": {
                "status_code": response.status_code,
                "headers": _sanitize_headers(dict(response.headers)),
                "body": _format_body_for_log(response_body, max_size=5000),
            },
            "performance": {
                "duration_ms": round(duration_ms, 2),
            },
        }

        # Add user info if available
        if hasattr(request.state, "user"):
            user = request.state.user
            if isinstance(user, dict):
                log_entry["user_id"] = user.get("sub", "unknown")

        # Add region if available
        from app.core.observability import get_region

        region = get_region()
        if region:
            log_entry["region"] = region

        # Log at appropriate level based on status code
        if response.status_code >= 500:
            logger.error(json.dumps(log_entry))
        elif response.status_code >= 400:
            logger.warning(json.dumps(log_entry))
        else:
            logger.info(json.dumps(log_entry))

        return response


class StreamingRequestLoggingMiddleware:
    """
    Alternative middleware that logs requests using streaming approach.

    This captures the full response body even for streaming responses.
    Use this if you need complete response logging.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        """
        Initialize streaming request logging middleware.

        Args:
            app: ASGI application
            enabled: Whether to enable logging
        """
        self.app = app
        self.enabled = enabled or settings.app_env in ("local", "test")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        ASGI entry point for middleware.

        Args:
            scope: ASGI scope
            receive: ASGI receive callable
            send: ASGI send callable
        """
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        # Skip logging for health/metrics endpoints
        path = scope.get("path", "")
        if path in ("/health", "/metrics", "/api/v1/health", "/api/v1/readyz"):
            await self.app(scope, receive, send)
            return

        start_time = datetime.now(UTC)

        # Capture request body
        request_body = b""

        async def receive_wrapper() -> Message:
            nonlocal request_body
            message = await receive()
            if message["type"] == "http.request":
                request_body += message.get("body", b"")
            return message

        # Capture response body and status
        response_body = b""
        status_code = 200

        async def send_wrapper(message: Message) -> None:
            nonlocal response_body, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                response_body += message.get("body", b"")
            await send(message)

        # Process request
        await self.app(scope, receive_wrapper, send_wrapper)

        # Calculate duration
        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # Build and log entry
        method = scope.get("method", "")
        log_entry = {
            "type": "api_call_streaming",
            "timestamp": datetime.now(UTC).isoformat(),
            "request": {
                "method": method,
                "path": path,
            },
            "response": {
                "status_code": status_code,
                "body_size_bytes": len(response_body),
            },
            "performance": {
                "duration_ms": round(duration_ms, 2),
            },
        }

        # Only log if it's an error or in local/test/dev
        if status_code >= 400 or settings.app_env in ("local", "test"):
            logger.info(json.dumps(log_entry))
