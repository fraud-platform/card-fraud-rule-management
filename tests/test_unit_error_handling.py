"""
Tests for error handling and sanitization.

Tests cover:
- Error sanitization in production vs development
- SQL query redaction
- File path redaction
- Schema detail redaction
"""

from unittest.mock import patch

import pytest

from app.core.errors import FraudGovError
from app.main import _sanitize_error_details


class TestSanitizeErrorDetails:
    """Tests for the _sanitize_error_details function."""

    @pytest.mark.anyio
    async def test_returns_all_details_in_non_production(self):
        """Test that all details are returned in non-production environments."""
        details = {
            "message": "Something went wrong",
            "file_path": "/app/app/main.py",
            "sql_query": "SELECT * FROM users WHERE id = 1",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "local"

            result = _sanitize_error_details(details)

            assert result == details
            assert result["file_path"] == "/app/app/main.py"
            assert result["sql_query"] == "SELECT * FROM users WHERE id = 1"

    @pytest.mark.anyio
    async def test_returns_all_details_in_test_environment(self):
        """Test that all details are returned in test environment."""
        details = {
            "message": "Test error",
            "internal_details": "secret",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "test"

            result = _sanitize_error_details(details)

            assert result == details

    @pytest.mark.anyio
    async def test_redacts_file_paths_in_production(self):
        """Test that file paths are redacted in production."""
        details = {
            "error": "Database connection failed",
            "file": "/app/app/db/session.py",
            "line": 42,
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["error"] == "Database connection failed"
            assert result["line"] == 42
            assert result["file"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_windows_style_file_paths(self):
        """Test that Windows file paths are redacted."""
        details = {
            "location": "C:\\Users\\test\\app\\main.py",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["location"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_unix_style_file_paths(self):
        """Test that Unix file paths are redacted."""
        details = {
            "location": "/home/user/app/main.py",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["location"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_sql_select_queries(self):
        """Test that SELECT queries are redacted."""
        details = {
            "query": "SELECT * FROM fraud_gov.rules WHERE status = 'ACTIVE'",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["query"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_sql_insert_queries(self):
        """Test that INSERT queries are redacted."""
        details = {
            "query": "INSERT INTO fraud_gov.rules (rule_name, status) VALUES ('test', 'DRAFT')",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["query"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_sql_update_queries(self):
        """Test that UPDATE queries are redacted."""
        details = {
            "query": "UPDATE fraud_gov.rules SET status = 'ACTIVE' WHERE rule_id = '123'",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["query"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_sql_delete_queries(self):
        """Test that DELETE queries are redacted."""
        details = {
            "query": "DELETE FROM fraud_gov.rules WHERE rule_id = '123'",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["query"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_schema_references(self):
        """Test that schema references are redacted."""
        details = {
            "info": "schema: fraud_gov",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["info"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_table_references(self):
        """Test that table references are redacted."""
        details = {
            "table_name": "table: rules",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["table_name"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_redacts_case_insensitive_sql(self):
        """Test that SQL matching is case insensitive."""
        details = {
            "query": "select * from users where id = 1",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["query"] == "[REDACTED]"

    @pytest.mark.anyio
    async def test_sanitizes_nested_dictionaries(self):
        """Test that nested dictionaries are sanitized."""
        details = {
            "outer": {
                "inner": {
                    "file": "/app/app/main.py",
                    "safe": "keep this",
                }
            },
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["outer"]["inner"]["file"] == "[REDACTED]"
            assert result["outer"]["inner"]["safe"] == "keep this"

    @pytest.mark.anyio
    async def test_sanitizes_lists(self):
        """Test that lists of dictionaries are sanitized."""
        details = {
            "errors": [
                {"file": "/app/app/main.py", "message": "Error 1"},
                {"file": "/app/app/db.py", "message": "Error 2"},
            ]
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["errors"][0]["file"] == "[REDACTED]"
            assert result["errors"][0]["message"] == "Error 1"
            assert result["errors"][1]["file"] == "[REDACTED]"
            assert result["errors"][1]["message"] == "Error 2"

    @pytest.mark.anyio
    async def test_preserves_non_string_values(self):
        """Test that non-string values are preserved."""
        details = {
            "count": 42,
            "active": True,
            "ratio": 3.14,
            "data": None,
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["count"] == 42
            assert result["active"] is True
            assert result["ratio"] == 3.14
            assert result["data"] is None

    @pytest.mark.anyio
    async def test_preserves_safe_string_values(self):
        """Test that safe string values are preserved."""
        details = {
            "error_type": "ValidationError",
            "field_name": "rule_name",
            "message": "Rule name is required",
        }

        with patch("app.main.settings") as mock_settings:
            mock_settings.app_env = "prod"

            result = _sanitize_error_details(details)

            assert result["error_type"] == "ValidationError"
            assert result["field_name"] == "rule_name"
            assert result["message"] == "Rule name is required"


class TestFraudGovError:
    """Tests for FraudGovError."""

    @pytest.mark.anyio
    async def test_fraud_gov_error_creation(self):
        """Test creating a FraudGovError."""
        error = FraudGovError(
            message="Test error",
            details={"key": "value"},
        )

        assert error.message == "Test error"
        assert error.details == {"key": "value"}

    @pytest.mark.anyio
    async def test_fraud_gov_error_with_no_details(self):
        """Test FraudGovError with no details."""
        error = FraudGovError(message="Simple error")

        assert error.message == "Simple error"
        assert error.details == {}
