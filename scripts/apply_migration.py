#!/usr/bin/env python3
"""
Apply database migrations.

This script applies SQL migration files to the database.
Usage:
    uv run python scripts/apply_migration.py <migration_file>
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg

from app.core.config import settings


def apply_migration(migration_file: str) -> None:
    """
    Apply a migration file to the database.

    Args:
        migration_file: Path to the migration SQL file
    """
    migration_path = Path(migration_file)

    if not migration_path.exists():
        print(f"Error: Migration file not found: {migration_file}")
        sys.exit(1)

    print(f"Applying migration: {migration_file}")

    # Read migration SQL
    with open(migration_path) as f:
        migration_sql = f.read()

    # Connect to database
    print("Connecting to database...")
    conn = psycopg.connect(settings.database_url_app)
    cursor = conn.cursor()

    try:
        # Execute migration
        cursor.execute(migration_sql)
        conn.commit()

        print(f"Successfully applied migration: {migration_file}")
    except Exception as e:
        conn.rollback()
        print(f"Error applying migration: {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python apply_migration.py <migration_file>")
        sys.exit(1)

    apply_migration(sys.argv[1])
