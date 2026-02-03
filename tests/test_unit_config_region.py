"""
Unit tests for APP_REGION configuration and validation (P0 feature).

Tests cover:
- APP_REGION field validation (format, required)
- Region-database URL matching validation
- Region context in observability
- Production environment enforcement
"""

import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestAppRegionValidation:
    """Tests for APP_REGION configuration validation."""

    @pytest.mark.anyio
    async def test_app_region_required(self):
        """Test that APP_REGION is a required configuration field."""
        # APP_REGION has a default value of "local" so it won't fail if not set
        # But we should validate the default is applied
        # Clear environment variable to test the default value
        original_region = os.environ.pop("APP_REGION", None)
        try:
            settings = Settings(
                app_env="local",
                database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
                auth0_domain="https://test.auth0.com",
                auth0_audience="test",
            )
            assert settings.app_region == "LOCAL"  # Default value is normalized to uppercase
        finally:
            if original_region is not None:
                os.environ["APP_REGION"] = original_region

    @pytest.mark.anyio
    async def test_app_region_normalized_to_uppercase(self):
        """Test that APP_REGION is normalized to uppercase."""
        settings = Settings(
            app_env="local",
            app_region="us-east-1",
            database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
            auth0_domain="https://test.auth0.com",
            auth0_audience="test",
        )
        assert settings.app_region == "US-EAST-1"

    @pytest.mark.anyio
    async def test_app_region_whitespace_trimmed(self):
        """Test that APP_REGION whitespace is trimmed."""
        settings = Settings(
            app_env="local",
            app_region="  us-east-1  ",
            database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
            auth0_domain="https://test.auth0.com",
            auth0_audience="test",
        )
        assert settings.app_region == "US-EAST-1"

    @pytest.mark.anyio
    async def test_app_region_invalid_format_raises_error(self):
        """Test that invalid APP_REGION format raises ValidationError."""
        # Test with special characters that are not allowed
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="local",
                app_region="invalid@region#",
                database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
                auth0_domain="https://test.auth0.com",
                auth0_audience="test",
            )
        assert "app_region" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_app_region_empty_raises_error(self):
        """Test that empty APP_REGION raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="local",
                app_region="",
                database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
                auth0_domain="https://test.auth0.com",
                auth0_audience="test",
            )
        assert "app_region" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_app_region_whitespace_only_raises_error(self):
        """Test that whitespace-only APP_REGION raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="local",
                app_region="   ",
                database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
                auth0_domain="https://test.auth0.com",
                auth0_audience="test",
            )
        assert "app_region" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_app_region_valid_formats(self):
        """Test that valid APP_REGION formats are accepted."""
        valid_regions = [
            "us-east-1",
            "US-EAST-1",
            "eu-west-1",
            "ap-southeast-1",
            "us",
            "EU",
            "apac",
            "LATAM",
            "us_east_1",
            # Note: dots are not supported in region names (only hyphens and underscores)
        ]

        for region in valid_regions:
            settings = Settings(
                app_env="local",
                app_region=region,
                database_url_app="postgresql://user:pass@localhost/db?sslmode=require",
                auth0_domain="https://test.auth0.com",
                auth0_audience="test",
            )
            # Should normalize to uppercase
            assert settings.app_region == region.upper()


class TestDatabaseRegionValidation:
    """Tests for database-region validation."""

    @pytest.mark.anyio
    async def test_local_environment_skips_region_validation(self):
        """Test that local environment skips database region validation."""
        # In local, any database URL should be accepted
        settings = Settings(
            app_env="local",
            app_region="us-east-1",
            database_url_app="postgresql://user:pass@unrelated-host/db?sslmode=require",
            auth0_domain="https://test.auth0.com",
            auth0_audience="test",
        )
        assert settings.app_region == "US-EAST-1"

    @pytest.mark.anyio
    async def test_region_validation_no_op_for_test_env(self):
        """Test that region validation is a no-op in test environment (managed via Doppler)."""
        import warnings

        # Region validation is now a no-op - region is managed via Doppler config
        # DB URLs do not contain region identifiers
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            settings = Settings(
                app_env="test",
                app_region="india",
                database_url_app="postgresql://user:pass@test-db.example.com/db?sslmode=require",
                auth0_domain="https://test.auth0.com",
                auth0_audience="test",
            )
            # No warning should be issued (validation is a no-op)
            region_warnings = [warning for warning in w if "region" in str(warning.message).lower()]
            assert len(region_warnings) == 0
            assert settings.app_region == "INDIA"

    @pytest.mark.anyio
    async def test_region_validation_no_op_for_production(self):
        """Test that region validation is a no-op in production (managed via Doppler)."""
        # Region is managed via Doppler config - no database hostname validation
        settings = Settings(
            app_env="prod",
            app_region="india",
            database_url_app="postgresql://user:pass@prod-db.example.com/db?sslmode=require",
            auth0_domain="https://test.auth0.com",
            auth0_audience="test",
            secret_key="a" * 32,  # Required for production
            cors_origins="https://example.com",  # No localhost for production
        )
        assert settings.app_region == "INDIA"

    @pytest.mark.anyio
    async def test_region_normalized_to_uppercase(self):
        """Test that region is normalized to uppercase regardless of database URL."""
        # Test environment with various region formats
        settings = Settings(
            app_env="test",
            app_region="us-west-2",
            database_url_app="postgresql://user:pass@some-db.example.com/db?sslmode=require",
            auth0_domain="https://test.auth0.com",
            auth0_audience="test",
        )
        assert settings.app_region == "US-WEST-2"


class TestRegionContextInObservability:
    """Tests for region context in observability system."""

    @pytest.mark.anyio
    async def test_region_set_from_settings_in_middleware(self):
        """Test that region is set from settings during request processing."""
        from app.core.config import settings
        from app.core.observability import get_region, set_region

        # Simulate what the middleware does
        set_region(settings.app_region)

        # Region should be set
        assert get_region() == settings.app_region

        # Clean up
        set_region("")

    @pytest.mark.anyio
    async def test_region_in_extract_request_context(self):
        """Test that region is included in request context extraction."""
        from fastapi import Request

        from app.core.observability import extract_request_context, set_region

        set_region("us-east-1")

        # Create a mock request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)

        context = extract_request_context(request)
        assert context["region"] == "us-east-1"

        # Clean up
        set_region("")
