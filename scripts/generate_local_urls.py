#!/usr/bin/env python3
"""
Generate local Docker connection strings for Doppler.

Usage:
    # Run with Doppler injecting the passwords
    doppler run --config local -- uv run python scripts/generate_local_urls.py

Output:
    Connection strings to copy into Doppler 'local' config:
    - DATABASE_URL_ADMIN
    - DATABASE_URL_APP
    - DATABASE_URL_ANALYTICS

Note:
    For local Docker, the connection strings are predictable (localhost:5432).
    This script just formats them correctly using the passwords from Doppler.
"""

from __future__ import annotations

import os
import sys


def generate_local_urls() -> int:
    """Generate and output local Docker connection strings."""
    # Read passwords from environment (Doppler injected)
    admin_pass = os.getenv("POSTGRES_ADMIN_PASSWORD", "postgres")
    app_pass = os.getenv("FRAUD_GOV_APP_PASSWORD", "")
    analytics_pass = os.getenv("FRAUD_GOV_ANALYTICS_PASSWORD", "")

    base = "postgresql://"
    host = "localhost:5432"
    database = "fraud_gov"

    print("=" * 78)
    print("LOCAL DOCKER CONNECTION STRINGS")
    print("=" * 78)
    print()
    print("Add these to Doppler 'local' config:")
    print()
    print("-" * 78)
    print()
    print("# Database URLs for local Docker development")
    print("# Generated for fraud-rule-management project")
    print()
    print("# NOTE: Use literal passwords (Doppler interpolation is optional)")
    print()
    print("# Admin connection (for schema setup, user management)")
    print(f"DATABASE_URL_ADMIN={base}postgres:{admin_pass}@{host}/{database}")
    print()
    print("# Application user (full CRUD access)")
    print(f"DATABASE_URL_APP={base}fraud_gov_app_user:{app_pass}@{host}/{database}")
    print()
    print("# Analytics user (read-only access)")
    print(
        f"DATABASE_URL_ANALYTICS={base}fraud_gov_analytics_user:{analytics_pass}@{host}/{database}"
    )
    print()
    print("-" * 78)
    print()
    print("Next steps:")
    print("1. Copy the above lines to Doppler 'local' config")
    print("2. Start local database: uv run db-local-up")
    print("3. Initialize schema: uv run python scripts/setup_database.py init --password-env")
    print()
    print("=" * 78)

    # Validate that passwords were provided (not empty)
    errors = []
    if not app_pass or app_pass == "YOUR_SECURE_PASSWORD":
        errors.append("  ⚠ FRAUD_GOV_APP_PASSWORD not set in Doppler 'local' config")
    if not analytics_pass or analytics_pass == "YOUR_SECURE_PASSWORD":
        errors.append("  ⚠ FRAUD_GOV_ANALYTICS_PASSWORD not set in Doppler 'local' config")

    if errors:
        print()
        print("WARNING: Some passwords are missing:")
        for error in errors:
            print(error)
        print()
        print("Please add these secrets to Doppler before proceeding.")
        return 1

    return 0


def main() -> int:
    """Entry point for the script."""
    try:
        return generate_local_urls()
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return 130
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
