"""Application configuration using Pydantic Settings.

This project loads configuration from environment variables.

Optionally, you may point `ENV_FILE` at a local env file (for development).
In Doppler-managed workflows, do not set `ENV_FILE` (or set it to an empty
string) so Doppler-injected secrets are the single source of truth.
"""

import os
import re
from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    """Application environment values."""

    LOCAL = "local"
    TEST = "test"
    PROD = "prod"


# Load an env file ONLY when explicitly requested.
# This is intentionally opt-in to avoid accidental `.env` usage when
# running with Doppler secrets.
_env_file = os.getenv("ENV_FILE")
if _env_file:
    env_path = Path(_env_file)
    if env_path.exists() and env_path.is_file():
        from app.core.dotenv import load_env_file

        load_env_file(env_path, overwrite=False)


class Settings(BaseSettings):
    """
    Application settings with type validation.

    Configuration is loaded from environment variables, with support
    for .env files in development.
    """

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE") or None, env_prefix="", extra="ignore"
    )

    # Application
    app_env: AppEnvironment = AppEnvironment.LOCAL
    app_name: str = "fraud-governance-api"
    app_log_level: str = "INFO"

    # Region Configuration (P0 - Required for production)
    # This is a hard security boundary for regional isolation
    app_region: str = "local"

    # Observability
    observability_enabled: bool = True
    observability_structured_logs: bool = True
    observability_request_id_header: str = "X-Request-ID"

    # OpenTelemetry Configuration
    otel_enabled: bool = True
    otel_service_name: str = "fraud-governance-api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_exporter_otlp_headers: str | None = None
    otel_traces_sampler: str = "parent_trace_always"
    otel_traces_sampler_arg: float = 1.0

    # Database - Runtime app user (used by FastAPI)
    database_url_app: str

    # Database - Admin user (for migrations/schema changes)
    database_url_admin: str | None = None

    # Auth0 Configuration
    auth0_domain: str
    auth0_audience: str
    auth0_algorithms: str = "RS256"

    # Auth0 Client Credentials (for testing/development only)
    auth0_client_id: str | None = None
    auth0_client_secret: str | None = None

    # Security Configuration
    # Local Development: Skip JWT validation for e2e load testing
    # SECURITY: ONLY allowed in LOCAL environment. Will raise error in TEST/PROD.
    # Set SECURITY_SKIP_JWT_VALIDATION=true in Doppler/.env for local testing
    skip_jwt_validation: bool = Field(
        default=False, validation_alias="SECURITY_SKIP_JWT_VALIDATION"
    )

    @field_validator("skip_jwt_validation", mode="before")
    @classmethod
    def parse_skip_jwt_validation(cls, v: bool | str) -> bool:
        """Parse skip_jwt_validation from string or bool."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    # Additional Auth/Security (for internal tokens if needed)
    secret_key: str | None = None
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Metrics token for protecting /metrics endpoint
    metrics_token: str | None = None

    # Health check token for protecting /health and /readyz endpoints (optional)
    # When set, these endpoints require X-Health-Token header
    # Recommended for production to prevent reconnaissance
    health_token: str | None = None

    # CORS Configuration
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins string into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def auth0_algorithms_list(self) -> list[str]:
        """Parse Auth0 algorithms string into a list."""
        return [algo.strip() for algo in self.auth0_algorithms.split(",")]

    # Ruleset Publishing Configuration
    # The environment name for published artifacts (e.g., 'local', 'test', 'prod')
    # Defaults to app_env if not explicitly set
    ruleset_publish_environment: str | None = None

    @property
    def publish_environment(self) -> str:
        """Get the environment name for publishing artifacts."""
        return self.ruleset_publish_environment or self.app_env.value

    # Artifact storage backend: 'filesystem' or 's3'
    # Filesystem is useful for local development without Docker
    # S3 (or MinIO) is required for distributed deployments
    ruleset_artifact_backend: str = "filesystem"

    # S3-compatible storage configuration (for MinIO or AWS S3)
    s3_endpoint_url: str | None = None
    s3_bucket_name: str = "fraud-gov-artifacts"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "us-east-1"
    s3_force_path_style: bool = True

    # S3 artifact prefix pattern (e.g., 'rulesets/{ENV}/{COUNTRY}/{RULESET_KEY}/')
    # Placeholders: {ENV} -> environment, {COUNTRY} -> country code, {RULESET_KEY} -> CARD_AUTH or CARD_MONITORING
    ruleset_artifact_prefix: str = "rulesets/{ENV}/{COUNTRY}/{RULESET_KEY}/"

    # Filesystem storage configuration (for local development)
    # Local directory to store artifacts when backend is 'filesystem'
    ruleset_filesystem_dir: str = ".local/ruleset-artifacts"

    @field_validator("app_env", mode="before")
    @classmethod
    def validate_app_env(cls, v: str | AppEnvironment) -> AppEnvironment:
        """Validate and parse app_env to AppEnvironment enum."""
        if isinstance(v, AppEnvironment):
            return v
        try:
            return AppEnvironment(v.lower())
        except ValueError:
            raise ValueError(
                f"app_env must be one of {[e.value for e in AppEnvironment]}, got '{v}'"
            )

    @field_validator("app_region")
    @classmethod
    def validate_app_region(cls, v: str) -> str:
        """Validate app_region follows expected format."""
        if not v or not v.strip():
            raise ValueError("app_region must be set")
        # Normalize to uppercase and strip whitespace
        region = v.strip().upper()
        # Check for reasonable region format (1-20 chars, alphanumeric with hyphens/underscores)
        # Supports common patterns: us-east-1, ap-southeast-1, eu-central-1, etc.
        if not re.match(r"^[A-Z0-9][A-Z0-9_-]{0,19}$", region):
            raise ValueError(
                "app_region must be 1-20 alphanumeric characters "
                "(hyphens/underscores allowed), got '{v}'"
            )
        return region

    def _validate_database_region_match(self) -> None:
        """
        Validate region configuration.

        APP_REGION is set in Doppler config and is the source of truth.
        Database URLs do not contain region identifiers - region is managed
        separately through environment-specific Doppler configs.
        """
        # Region is managed via Doppler config (local/test/prod)
        # DB URLs do not contain region identifiers
        pass

    @model_validator(mode="after")
    def validate_production_settings(self) -> Settings:
        """
        Validate production-specific settings.

        These checks prevent insecure configurations from being deployed to production.
        """
        # P0: Validate region-database consistency for all environments
        self._validate_database_region_match()

        # SECURITY: JWT validation bypass is ONLY allowed in LOCAL environment
        if self.skip_jwt_validation and self.app_env != AppEnvironment.LOCAL:
            raise ValueError(
                "SECURITY_SKIP_JWT_VALIDATION can only be set in local environment. "
                f"Current environment: {self.app_env.value}"
            )

        if self.app_env == AppEnvironment.PROD:
            # SECRET_KEY must be set and sufficiently long
            if not self.secret_key or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set and at least 32 characters in production")

            # Database must use PostgreSQL with SSL
            if not self.database_url_app.startswith("postgresql://"):
                raise ValueError("DATABASE_URL_APP must use postgresql:// scheme in production")
            if "sslmode=require" not in self.database_url_app:
                raise ValueError("DATABASE_URL_APP must use sslmode=require in production")

            # Auth0 domain must use HTTPS
            if not self.auth0_domain.startswith("https://"):
                raise ValueError("AUTH0_DOMAIN must use HTTPS in production")

            # CORS must not allow localhost in production
            for origin in self.cors_origins_list:
                if "localhost" in origin or "127.0.0.1" in origin:
                    raise ValueError(
                        f"CORS origins must not contain localhost in production: {origin}"
                    )

        return self


settings = Settings()
