"""
Pytest HTML report enhancements for better visibility of logs and API calls.

This module provides:
1. Custom JSON formatter for structured logs with proper indentation
2. Request/response logging utilities for tests
3. logged_client fixture that captures API calls

Usage:
    Use the `logged_client` fixture instead of `client` to capture API calls:
    def test_something(logged_client):
        response = logged_client.get("/api/v1/rules")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import pytest

_api_calls_by_test: dict[str, list[dict[str, Any]]] = {}


def format_json_pretty(data: Any, indent: int = 2) -> str:
    """Format JSON data with proper indentation for readability."""
    if data is None:
        return "null"
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return json.dumps(parsed, indent=indent, sort_keys=True)
        except (json.JSONDecodeError, TypeError):
            return json.dumps(data, indent=indent)
    return json.dumps(data, indent=indent, sort_keys=True)


class TestJSONFormatter(logging.Formatter):
    """JSON formatter that renders nicely in pytest output."""

    def format(self, record: logging.LogRecord) -> str:
        level_color = {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
            "CRITICAL": "\033[35m",
        }.get(record.levelname, "")
        reset = "\033[0m"

        msg = record.getMessage()

        extra_parts = []
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
                "exc_info",
                "exc_text",
                "stack_info",
                "colorama",
            }:
                if isinstance(value, (dict, list)):
                    extra_parts.append(f"{key}={format_json_pretty(value, indent=2)}")
                elif value and not str(value).startswith("<"):
                    extra_parts.append(f"{key}={value}")

        if extra_parts:
            msg = f"{msg}\n  " + "\n  ".join(extra_parts)

        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        return f"{level_color}[{timestamp}] [{record.levelname}]{reset} {record.name}: {msg}"


def configure_test_logging():
    """Configure logging for tests with custom formatter."""
    if "PYTEST_CURRENT_TEST" in os.environ:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        handler = logging.StreamHandler()
        handler.setFormatter(TestJSONFormatter())
        root_logger.addHandler(handler)


configure_test_logging()


class APICallLogger:
    """Context manager for logging API calls during tests."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.calls: list[dict[str, Any]] = []
        if test_name not in _api_calls_by_test:
            _api_calls_by_test[test_name] = self.calls
        else:
            self.calls = _api_calls_by_test[test_name]

    def log_request(
        self,
        method: str,
        path: str,
        headers: dict | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        """Log an API request."""
        call_data = {
            "type": "request",
            "method": method,
            "path": path,
            "headers": self._sanitize_headers(headers or {}),
            "body": self._format_body(body),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.calls.append(call_data)
        return call_data

    def log_response(
        self,
        status_code: int,
        headers: dict | None = None,
        body: Any = None,
        duration_ms: float | None = None,
    ) -> dict[str, Any]:
        """Log an API response."""
        call_data = {
            "type": "response",
            "status_code": status_code,
            "headers": self._sanitize_headers(headers or {}),
            "body": self._format_body(body),
            "duration_ms": duration_ms,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.calls.append(call_data)
        return call_data

    def log_error(
        self,
        error_type: str,
        message: str,
        details: dict | None = None,
    ) -> dict[str, Any]:
        """Log an API error."""
        call_data = {
            "type": "error",
            "error_type": error_type,
            "message": message,
            "details": details,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.calls.append(call_data)
        return call_data

    def get_summary(self) -> str:
        """Get a formatted summary of all API calls."""
        if not self.calls:
            return "No API calls captured"

        lines = ["\n" + "=" * 60, "API Calls Summary", "=" * 60]
        for i, call in enumerate(self.calls, 1):
            if call["type"] == "request":
                lines.append(f"\n{i}. REQUEST: {call['method']} {call['path']}")
                if call.get("body"):
                    lines.append(f"   Body: {format_json_pretty(call['body'], indent=2)}")
            elif call["type"] == "response":
                lines.append(
                    f"   RESPONSE: {call['status_code']} ({call.get('duration_ms', 0):.0f}ms)"
                )
                if call.get("body"):
                    lines.append(f"   Body: {format_json_pretty(call['body'], indent=2)}")
            elif call["type"] == "error":
                lines.append(f"   ERROR: {call['error_type']}: {call['message']}")

        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def _format_body(body: Any) -> Any:
        """Format body for display."""
        if body is None:
            return None
        if isinstance(body, str):
            try:
                return json.loads(body)
            except (json.JSONDecodeError, TypeError):
                return body
        return body

    @staticmethod
    def _sanitize_headers(headers: dict) -> dict:
        """Remove sensitive headers."""
        sanitized = {}
        sensitive_keys = {"authorization", "cookie", "x-api-key"}
        for k, v in headers.items():
            if k.lower() in sensitive_keys:
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = v
        return sanitized


def get_api_logger(test_name: str) -> APICallLogger:
    """Get an API call logger for the current test."""
    return APICallLogger(test_name)


@pytest.fixture
def logged_client(db_session, request):
    """
    TestClient that logs all API requests/responses.

    Captures and displays API call information in test output.
    Use this instead of `client` for better debugging.
    """
    import time
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.core.db import get_db_session
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: (yield db_session)

    test_name = f"{request.module.__name__}::{request.function.__name__}"
    api_logger = get_api_logger(test_name)

    original_request = TestClient.request

    def logged_request(self, method, url, **kwargs):
        """Wrapper that logs all requests/responses."""
        start = time.time()
        api_logger.log_request(
            method=method.upper(),
            path=str(url),
            headers=kwargs.get("headers"),
            body=kwargs.get("json") or kwargs.get("data"),
        )

        response = original_request(self, method, url, **kwargs)

        duration_ms = (time.time() - start) * 1000
        try:
            response_body = response.json()
        except Exception:
            response_body = response.text[:1000] if response.text else None

        api_logger.log_response(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response_body,
            duration_ms=round(duration_ms, 2),
        )

        return response

    with patch.object(TestClient, "request", logged_request):
        client = TestClient(app)
        yield client
        print(api_logger.get_summary())


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print summary of API calls after all tests complete."""
    total_calls = sum(len(calls) for calls in _api_calls_by_test.values())

    if total_calls > 0 and terminalreporter.verbosity >= 2:
        terminalreporter.write_sep("=", f"Total API calls captured: {total_calls}")
