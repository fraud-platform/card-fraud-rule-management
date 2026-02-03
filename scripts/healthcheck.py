#!/usr/bin/env python3
"""
Simple health check script for Fraud Governance API.

Returns exit code 0 if healthy, 1 otherwise.

Usage:
    # Check default (localhost:8000)
    uv run python scripts/healthcheck.py

    # Check specific URL
    uv run python scripts/healthcheck.py http://localhost:8001

    # Use in Docker health check
    HEALTHCHECK CMD python scripts/healthcheck.py http://localhost:8000

Exit Codes:
    0 - API is healthy
    1 - API is unhealthy or unreachable
    2 - Invalid arguments
"""

from __future__ import annotations

import sys

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: uv sync --extra dev")
    sys.exit(2)


def check_health(base_url: str, timeout: float = 5.0) -> bool:
    """Check if the API health endpoint returns 200.

    Args:
        base_url: Base URL of the API (e.g., "http://localhost:8000")
        timeout: Request timeout in seconds

    Returns:
        True if healthy, False otherwise
    """
    health_url = f"{base_url.rstrip('/')}/api/v1/health"

    try:
        response = httpx.get(health_url, timeout=timeout)
        return response.status_code == 200
    except httpx.RequestError:
        return False


def main() -> int:
    """Main entry point."""
    # Default URL
    base_url = "http://localhost:8000"

    # Parse arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-h", "--help"):
            print(__doc__)
            return 0
        base_url = arg

    # Check health
    if check_health(base_url):
        print(f"OK: {base_url} is healthy")
        return 0
    else:
        print(f"FAIL: {base_url} is unhealthy or unreachable")
        return 1


if __name__ == "__main__":
    sys.exit(main())
