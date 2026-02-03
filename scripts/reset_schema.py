#!/usr/bin/env python3
"""
Reset database schema - DROPS and RECREATES fraud_gov schema from scratch.

⚠️  DESTRUCTIVE: This will DELETE ALL DATA in the fraud_gov schema.

NOTE: This script is DEPRECATED. Use setup_database.py instead:
    uv run python scripts/setup_database.py reset --mode schema

When to use:
- Initial database setup (first time on a database)
- Schema has major changes and you want to start fresh
- Test database cleanup (safe for pytest/test databases)

When NOT to use:
- Production databases with existing data (use setup_database.py instead)

Environment Files (select one with --env-file):
    .env         → Development environment (default)
    .env.test    → Pytest testing environment

Usage:
    # Default: Uses .env
    uv run python scripts/reset_schema.py

    # For pytest: Use test environment
    uv run python scripts/reset_schema.py --env-file .env.test

    # For production: Use production env
    uv run python scripts/reset_schema.py --env-file .env.production

Dependencies:
    1. Users must exist first → Run setup_database.py create-users
    2. .env file must be configured with DATABASE_URL_ADMIN
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg

# Add app to path for imports
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.core.dotenv import (  # noqa: E402 (import after path setup)
    find_env_file,
    load_env_file,
)


def is_safe_database(db_url: str) -> bool:
    """Check if database name looks like a test/dev database."""
    db_name = db_url.split("/")[-1].split("?")[0].lower()
    safe_keywords = ["test", "dev", "pytest", "local", "sandbox"]
    return any(keyword in db_name for keyword in safe_keywords)


def fresh_setup(admin_url: str, confirm: bool = False, force: bool = False) -> int:
    """Drop and recreate the fraud_gov schema from scratch."""
    print("\n" + "=" * 60)
    print("FRESH DATABASE SETUP")
    print("=" * 60)
    print()
    print("WARNING: This will DELETE ALL DATA in fraud_gov schema")

    # Safety check (can be bypassed with --force)
    if not is_safe_database(admin_url):
        print()
        print("Database name does NOT contain 'test' or 'dev'")
        print(f"DB: {admin_url.split('@')[-1]}")
        print()
        if force:
            print("WARNING: --force flag set, skipping safety check")
        else:
            response = input("Type 'DELETE-PRODUCTION-DATA' to continue: ")
            if response != "DELETE-PRODUCTION-DATA":
                print("Setup cancelled.")
                return 1

    print()

    if not confirm and not force:
        response = input("Proceed with fresh setup? [y/N] ")
        if response.lower() not in ("y", "yes"):
            print("Setup cancelled.")
            return 0

    try:
        with psycopg.connect(admin_url, autocommit=False) as conn:
            print("\n[1/5] Dropping schema...")
            conn.execute("DROP SCHEMA IF EXISTS fraud_gov CASCADE;")
            conn.commit()
            print("   [OK] Schema dropped")

            print("\n[2/5] Creating schema (types, tables, indexes, RLS)...")
            schema_sql = (ROOT / "db" / "fraud_governance_schema.sql").read_text(encoding="utf-8")
            conn.execute(schema_sql)
            conn.commit()
            print("   [OK] Schema created")

            print("\n[3/5] Verifying users...")
            result = conn.execute(
                "SELECT rolname FROM pg_roles WHERE rolname IN ('fraud_gov_app_user', 'fraud_gov_analytics_user')"
            ).fetchall()
            users = [row[0] for row in result]
            if sorted(users) != ["fraud_gov_analytics_user", "fraud_gov_app_user"]:
                print(f"   [ERROR] Users not found: {users}")
                print()
                print("Create users first:")
                print("  uv run python scripts/setup_database.py create-users --password-env")
                print()
                print("Or with Doppler:")
                print(
                    "  doppler run --config <env> -- uv run python scripts/setup_database.py create-users --password-env"
                )
                return 1
            print(f"   [OK] Users found: {', '.join(users)}")

            print("\n[4/5] Applying seed data...")
            seed_sql = (ROOT / "db" / "seed_rule_fields.sql").read_text(encoding="utf-8")
            conn.execute(seed_sql)
            conn.commit()
            print("   [OK] Seed data applied")

            print("\n[5/5] Verifying installation...")
            tables = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'fraud_gov' ORDER BY tablename"
            ).fetchall()
            table_names = [row[0] for row in tables]
            print(f"   [OK] {len(table_names)} tables created: {', '.join(table_names)}")

    except psycopg.Error as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return 1

    print()
    print("=" * 60)
    print("[OK] FRESH SETUP COMPLETE")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset fraud_gov schema from scratch (keeps users)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to .env file (default: .env for dev, .env.test for testing)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Skip confirmation prompts (useful for CI/CD or known test databases)",
    )

    args = parser.parse_args()

    # Determine which env file to use
    env_file = args.env_file or os.environ.get("ENV_FILE") or find_env_file()
    if not env_file:
        env_file = ".env"  # default

    print(f"Using environment file: {env_file}")
    print()

    load_env_file(env_file)

    admin_url = os.getenv("DATABASE_URL_ADMIN")
    if not admin_url:
        print("ERROR: DATABASE_URL_ADMIN not set in environment file")
        return 1

    return fresh_setup(admin_url, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
