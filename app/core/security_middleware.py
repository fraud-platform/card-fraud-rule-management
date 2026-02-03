"""
Security headers middleware for FastAPI.

Adds security headers to all responses:
- Strict-Transport-Security (HSTS)
- X-Frame-Options
- Content-Security-Policy (CSP)
- X-Content-Type-Options
- X-XSS-Protection
- Referrer-Policy
- Permissions-Policy
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Paths that should have relaxed security (docs, OpenAPI schema)
DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all HTTP responses.

    Headers added:
    - Strict-Transport-Security: Enforces HTTPS connections
    - X-Frame-Options: Prevents clickjacking
    - Content-Security-Policy: Prevents XSS
    - X-Content-Type-Options: Prevents MIME-sniffing
    - X-XSS-Protection: Enables browser XSS filter
    - Referrer-Policy: Controls referrer information
    - Permissions-Policy: Controls browser features
    """

    def __init__(
        self,
        app: ASGIApp,
        hsts_max_age: int = 31536000,  # 1 year
        include_subdomains: bool = True,
        preload: bool = False,
    ) -> None:
        """
        Initialize security headers middleware.

        Args:
            app: ASGI application
            hsts_max_age: HSTS max-age in seconds (default 1 year)
            include_subdomains: Apply HSTS to all subdomains
            preload: Allow inclusion in HSTS preload list
        """
        super().__init__(app)
        self.hsts_max_age = hsts_max_age
        self.include_subdomains = include_subdomains
        self.preload = preload

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request and add security headers to response.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response with security headers added
        """
        response = await call_next(request)

        # Skip security headers for docs endpoints to allow Swagger UI to work
        is_docs_path = request.url.path in DOCS_PATHS

        # Strict-Transport-Security (HSTS)
        # Enforces HTTPS connections for the specified time
        hsts_value = f"max-age={self.hsts_max_age}"
        if self.include_subdomains:
            hsts_value += "; includeSubDomains"
        if self.preload:
            hsts_value += "; preload"
        response.headers["Strict-Transport-Security"] = hsts_value

        # X-Frame-Options
        # Prevents clickjacking by denying framing (skip for docs)
        if not is_docs_path:
            response.headers["X-Frame-Options"] = "DENY"

        # Content-Security-Policy
        # Prevents XSS by restricting resource sources
        # For docs endpoints, use a permissive policy to allow Swagger UI CDN
        if is_docs_path:
            csp_directives = [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
                "img-src 'self' data: https: https://fastapi.tiangolo.com",
                "font-src 'self' data: https://cdn.jsdelivr.net",
                "connect-src 'self'",
            ]
        else:
            csp_directives = [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # Needed for Swagger
                "style-src 'self' 'unsafe-inline'",  # Needed for Swagger
                "img-src 'self' data: https:",
                "font-src 'self' data:",
                "connect-src 'self'",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
            ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        # X-Content-Type-Options
        # Prevents MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-XSS-Protection
        # Enables browser's XSS filter (legacy, but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy
        # Controls how much referrer information is sent
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy (formerly Feature-Policy)
        # Controls browser features and APIs
        permissions_policy = [
            "geolocation=()",
            "microphone=()",
            "camera=()",
            "payment=()",
        ]
        response.headers["Permissions-Policy"] = ", ".join(permissions_policy)

        return response
