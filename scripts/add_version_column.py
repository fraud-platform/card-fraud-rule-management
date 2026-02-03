#!/usr/bin/env python3
"""
Add version column to rules and rulesets tables.

This script adds the version column for optimistic locking.
It's designed to work with both admin and app database users.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg

from app.core.config import settings


def add_version_column():
    """Add version column to rules and rulesets tables."""

    # Use admin URL if available, otherwise fall back to app URL
    db_url = settings.database_url_admin or settings.database_url_app

    print("Connecting to database...")
    print(f"Using {'admin' if settings.database_url_admin else 'app'} credentials...")
    conn = psycopg.connect(db_url)
    cursor = conn.cursor()

    try:
        # Check if version column exists in rules table
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'fraud_gov'
              AND table_name = 'rules'
              AND column_name = 'version'
        """)
        rules_version_exists = cursor.fetchone() is not None

        if not rules_version_exists:
            print("Adding version column to rules table...")
            cursor.execute("""
                ALTER TABLE fraud_gov.rules
                ADD COLUMN version INTEGER NOT NULL DEFAULT 1
            """)
            print("Added version column to rules table")

            # Add comment
            cursor.execute("""
                COMMENT ON COLUMN fraud_gov.rules.version IS
                'Optimistic locking version - increments on each update to detect concurrent modifications'
            """)
        else:
            print("Version column already exists in rules table")

        # Check if version column exists in rulesets table
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'fraud_gov'
              AND table_name = 'rulesets'
              AND column_name = 'version'
        """)
        rulesets_version_exists = cursor.fetchone() is not None

        if rulesets_version_exists:
            print("Version column already exists in rulesets table (serves dual purpose)")
        else:
            print("Note: RuleSet version column should already exist as part of the schema")

        # Create index on rules.version if it doesn't exist
        cursor.execute("""
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'fraud_gov'
              AND tablename = 'rules'
              AND indexname = 'idx_rules_version'
        """)
        index_exists = cursor.fetchone() is not None

        if not index_exists:
            print("Creating index on rules.version...")
            cursor.execute("""
                CREATE INDEX idx_rules_version
                ON fraud_gov.rules(version)
            """)
            print("Created index on rules.version")
        else:
            print("Index on rules.version already exists")

        conn.commit()
        print("\nMigration completed successfully!")

        # Verify
        cursor.execute("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_schema = 'fraud_gov'
              AND table_name = 'rules'
              AND column_name = 'version'
        """)
        result = cursor.fetchone()
        if result:
            print("\nVerification for rules.version:")
            print(f"  column_name: {result[0]}")
            print(f"  data_type: {result[1]}")
            print(f"  column_default: {result[2]}")

    except Exception as e:
        conn.rollback()
        print(f"\nError during migration: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    add_version_column()
