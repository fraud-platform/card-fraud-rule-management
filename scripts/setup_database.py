#!/usr/bin/env python3
"""
Fraud Governance API Database Setup

Automated database setup for PostgreSQL (local Docker, Neon, or any Postgres 18).

Usage:
    # First-time setup (interactive)
    doppler run --config <env> -- uv run python scripts/setup_database.py init

    # First-time setup (automated, passwords from Doppler)
    doppler run --config <env> -- uv run python scripts/setup_database.py init --password-env --yes

    # Reset database (drop schema)
    doppler run --config <env> -- uv run python scripts/setup_database.py reset --mode schema

    # Reset database (truncate data only)
    doppler run --config <env> -- uv run python scripts/setup_database.py reset --mode data

    # Seed data
    doppler run --config <env> -- uv run python scripts/setup_database.py seed --demo

    # Verify setup
    doppler run --config <env> -- uv run python scripts/setup_database.py verify

    # Create users only
    doppler run --config <env> -- uv run python scripts/setup_database.py create-users --password-env

Environment Variables (from Doppler):
    DATABASE_URL_ADMIN    - Admin connection (for schema/user management)
    DATABASE_URL_APP      - App user connection (for verification)
    FRAUD_GOV_APP_PASSWORD         - Password for app_user (for --password-env)
    FRAUD_GOV_ANALYTICS_PASSWORD    - Password for analytics_user (for --password-env)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Add app to path for imports
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ANSI colors for terminal output
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")


def log_success(msg: str) -> None:
    print(f"{Colors.GREEN}[OK]{Colors.END} {msg}")


def log_warning(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.END} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.END} {msg}")


def log_step(step: int, total: int, msg: str) -> None:
    print(f"\n{Colors.BOLD}[{step}/{total}] {msg}{Colors.END}")


@dataclass
class SetupResult:
    """Result of a setup step."""

    success: bool
    message: str
    details: str | None = None


class ResetMode(Enum):
    """Database reset modes."""

    SCHEMA = "schema"  # Drop and recreate schema
    DATA = "data"  # Truncate tables only


class DatabaseSetup:
    """Handles automated database setup for Fraud Governance API."""

    def __init__(
        self,
        admin_url: str,
        app_url: str | None = None,
        app_password: str | None = None,
        analytics_password: str | None = None,
    ):
        self.admin_url = admin_url
        self.app_url = app_url
        self.app_password = app_password
        self.analytics_password = analytics_password
        self.repo_root = Path(__file__).parent.parent

    def _load_sql_file(self, filename: str) -> str:
        """Load SQL file from db directory."""
        sql_path = self.repo_root / "db" / filename
        if not sql_path.exists():
            raise FileNotFoundError(f"SQL file not found: {sql_path}")
        return sql_path.read_text(encoding="utf-8")

    def _split_sql_statements(self, sql_content: str) -> list[str]:
        """Split SQL content into statements, preserving transaction blocks and dollar-quoted strings."""
        statements = []
        current = []
        in_transaction = False
        in_dollar_quote = False
        dollar_quote_tag = None
        in_block_comment = False  # Track /* */ style comments

        for line in sql_content.splitlines():
            stripped = line.strip()
            original_line = line  # Keep original for proper formatting

            # Handle block comments /* ... */
            while "/*" in stripped or in_block_comment:
                if in_block_comment:
                    if "*/" in stripped:
                        # End of block comment
                        end_idx = stripped.index("*/") + 2
                        # Remove the comment portion
                        after_comment = stripped[end_idx:].strip()
                        if after_comment:
                            stripped = after_comment
                        else:
                            stripped = ""
                        in_block_comment = False
                        continue
                    else:
                        # Entire line is within comment
                        stripped = ""
                        break
                else:
                    # Start of block comment
                    start_idx = stripped.index("/*")
                    before_comment = stripped[:start_idx].strip()
                    # Check if comment ends on same line
                    if "*/" in stripped[start_idx:]:
                        end_idx = stripped.index("*/", start_idx) + 2
                        after_comment = stripped[end_idx:].strip()
                        if before_comment:
                            stripped = before_comment + " " + after_comment
                        else:
                            stripped = after_comment if after_comment else ""
                        continue
                    else:
                        in_block_comment = True
                        stripped = before_comment
                        if stripped:
                            break
                        else:
                            # Nothing before comment start, skip line
                            stripped = ""
                            break

            # Skip empty lines and comments (unless inside a block)
            if not stripped or (
                stripped.startswith("--") and not (in_transaction or in_dollar_quote or current)
            ):
                if current:
                    current.append(original_line)  # Keep comments within statements
                continue

            # Track dollar-quoted strings (DO $$ blocks, $tag$ ... $tag$)
            if "$$" in stripped:
                if not in_dollar_quote:
                    in_dollar_quote = True
                    current.append(original_line)
                    continue
                else:
                    # Check if this is the closing $$
                    in_dollar_quote = False
                    current.append(original_line)
                    continue
            elif in_dollar_quote:
                current.append(original_line)
                continue

            # Check for custom dollar quote tags
            if "$" in stripped:
                # Opening tag like $func$
                if not in_dollar_quote and not in_transaction:
                    match = None
                    for tag in ["$func$", "$body$", "$table$", "$def$"]:
                        if tag in stripped:
                            match = tag
                            break
                    if match:
                        in_dollar_quote = True
                        dollar_quote_tag = match
                        current.append(original_line)
                        continue
                # Closing tag
                if in_dollar_quote and dollar_quote_tag and dollar_quote_tag in stripped:
                    in_dollar_quote = False
                    dollar_quote_tag = None
                    current.append(original_line)
                    continue

            # Track transactions
            if stripped.upper().startswith("BEGIN"):
                in_transaction = True
                current.append(original_line)
            elif stripped.upper().startswith("COMMIT"):
                current.append(original_line)
                in_transaction = False
                statements.append("\n".join(current))
                current = []
            # Statement terminator outside of transaction
            elif stripped.endswith(";"):
                current.append(original_line)
                if not in_transaction:
                    statements.append("\n".join(current))
                    current = []
            else:
                current.append(original_line)

        # Handle any remaining content (last statement without semicolon)
        if current and not in_transaction:
            content = "\n".join(current).strip()
            if content:
                statements.append(content)

        return statements

    def _execute_sql(
        self, conn: psycopg.Connection, sql_content: str, description: str
    ) -> SetupResult:
        """Execute SQL content with error handling."""
        try:
            statements = self._split_sql_statements(sql_content)

            for stmt in statements:
                if stmt.strip():
                    conn.execute(stmt)

            conn.commit()
            return SetupResult(
                success=True,
                message=description,
                details=f"Executed {len(statements)} statements",
            )
        except psycopg.Error as e:
            conn.rollback()
            return SetupResult(
                success=False,
                message=description,
                details=f"{type(e).__name__}: {e}",
            )

    def create_users(self, conn: psycopg.Connection) -> SetupResult:
        """Create database users with provided passwords.

        Note: Role grants are handled by fraud_governance_schema.sql (same as local Docker).
        The schema DDL creates roles and grants them to users after creating the roles.
        """
        if not self.app_password or not self.analytics_password:
            return SetupResult(
                success=False,
                message="Passwords not provided",
                details="Use --password-env flag or set passwords programmatically",
            )

        try:
            # Import for safe SQL literals
            from psycopg import sql

            # Create users if they don't exist
            conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fraud_gov_app_user') THEN
                        CREATE ROLE fraud_gov_app_user WITH LOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fraud_gov_analytics_user') THEN
                        CREATE ROLE fraud_gov_analytics_user WITH LOGIN;
                    END IF;
                END
                $$;
            """)

            # Set passwords using sql.Literal (required for ALTER ROLE)
            conn.execute(
                sql.SQL("ALTER ROLE fraud_gov_app_user WITH PASSWORD {}").format(
                    sql.Literal(self.app_password)
                )
            )
            conn.execute(
                sql.SQL("ALTER ROLE fraud_gov_analytics_user WITH PASSWORD {}").format(
                    sql.Literal(self.analytics_password)
                )
            )

            conn.commit()

            return SetupResult(
                success=True,
                message="Users created",
                details="fraud_gov_app_user, fraud_gov_analytics_user (role grants will be applied by schema DDL)",
            )
        except psycopg.Error as e:
            conn.rollback()
            return SetupResult(
                success=False,
                message="Failed to create users",
                details=f"{type(e).__name__}: {e}",
            )

    def verify_users(self, conn: psycopg.Connection) -> SetupResult:
        """Verify that database users exist."""
        try:
            result = conn.execute(
                """
                SELECT rolname FROM pg_roles
                WHERE rolname IN ('fraud_gov_app_user', 'fraud_gov_analytics_user')
                ORDER BY rolname
                """
            ).fetchall()

            actual_users = [row["rolname"] for row in result]
            required_users = ["fraud_gov_app_user", "fraud_gov_analytics_user"]
            missing = set(required_users) - set(actual_users)

            if missing:
                return SetupResult(
                    success=False,
                    message="Database users not found",
                    details=f"Missing users: {', '.join(missing)}",
                )

            return SetupResult(
                success=True,
                message="Database users verified",
                details=f"Found: {', '.join(actual_users)}",
            )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="Failed to verify users",
                details=f"{type(e).__name__}: {e}",
            )

    def verify_schema(self, conn: psycopg.Connection) -> SetupResult:
        """Verify that schema was created correctly."""
        try:
            result = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'fraud_gov' ORDER BY tablename"
            ).fetchall()

            expected_tables = [
                "rule_fields",
                "rule_field_metadata",
                "rule_field_versions",
                "rules",
                "rule_versions",
                "rulesets",
                "ruleset_versions",
                "ruleset_version_rules",
                "ruleset_manifest",
                "field_registry_manifest",
                "approvals",
                "audit_log",
            ]

            actual_tables = [row["tablename"] for row in result]
            missing = set(expected_tables) - set(actual_tables)

            if missing:
                return SetupResult(
                    success=False,
                    message="Schema verification failed",
                    details=f"Missing tables: {', '.join(missing)}",
                )

            return SetupResult(
                success=True,
                message="Schema verified",
                details=f"Found {len(actual_tables)} tables",
            )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="Schema verification failed",
                details=f"{type(e).__name__}: {e}",
            )

    def verify_indexes(self, conn: psycopg.Connection) -> SetupResult:
        """Verify that production indexes were created."""
        try:
            result = conn.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'fraud_gov'
                ORDER BY indexname
            """).fetchall()

            index_names = [row["indexname"] for row in result]

            # Check for key production indexes (updated for field registry versioning)
            key_indexes = [
                "idx_rules_status",
                "idx_rules_created_by",
                "idx_rule_versions_scope",  # GIN index with jsonb_path_ops
                "idx_rule_versions_pending_approval",  # Partial index for approval queue
                "idx_ruleset_versions_pending_approval",  # Partial index for approval queue
                "idx_ruleset_versions_ruleset_id",  # ruleset_versions table
                "idx_ruleset_version_rules_ruleset_version_id",  # renamed from ruleset_rules
                "idx_approvals_status_entity_type",
                "idx_audit_log_performed_by",
                "idx_ruleset_manifest_region_country",  # region/country lookup
                "idx_rule_fields_field_id",  # NEW: field ID lookup for engine
                "idx_rule_field_versions_status",  # NEW: field version status
                "idx_rule_field_versions_pending_approval",  # NEW: field version approval queue
                "idx_field_registry_manifest_version",  # NEW: registry version lookup
            ]

            missing = [idx for idx in key_indexes if idx not in index_names]

            if missing:
                return SetupResult(
                    success=False,
                    message="Index verification found missing indexes",
                    details=f"Missing: {', '.join(missing)}",
                )

            return SetupResult(
                success=True,
                message="Indexes verified",
                details=f"Found {len(index_names)} indexes",
            )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="Index verification failed",
                details=f"{type(e).__name__}: {e}",
            )

    def verify_triggers(self, conn: psycopg.Connection) -> SetupResult:
        """Verify that required triggers were created."""
        try:
            result = conn.execute("""
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE event_object_schema = 'fraud_gov'
                ORDER BY trigger_name
            """).fetchall()

            trigger_names = [row["trigger_name"] for row in result]

            # Check for key triggers
            key_triggers = [
                "trg_rules_updated_at",
                "trg_rulesets_updated_at",
                "trg_ruleset_version_rules_type_check",  # NEW: rule type consistency
            ]

            missing = [t for t in key_triggers if t not in trigger_names]

            if missing:
                return SetupResult(
                    success=False,
                    message="Trigger verification found missing triggers",
                    details=f"Missing: {', '.join(missing)}",
                )

            return SetupResult(
                success=True,
                message="Triggers verified",
                details=f"Found {len(trigger_names)} triggers",
            )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="Trigger verification failed",
                details=f"{type(e).__name__}: {e}",
            )

    def verify_functions(self, conn: psycopg.Connection) -> SetupResult:
        """Verify that required functions were created."""
        try:
            result = conn.execute("""
                SELECT routine_name
                FROM information_schema.routines
                WHERE routine_schema = 'fraud_gov'
                AND routine_type = 'FUNCTION'
                ORDER BY routine_name
            """).fetchall()

            func_names = [row["routine_name"] for row in result]

            # Check for key functions
            key_functions = [
                "update_updated_at",
                "check_rule_type_match",  # NEW: rule type consistency
            ]

            missing = [f for f in key_functions if f not in func_names]

            if missing:
                return SetupResult(
                    success=False,
                    message="Function verification found missing functions",
                    details=f"Missing: {', '.join(missing)}",
                )

            return SetupResult(
                success=True,
                message="Functions verified",
                details=f"Found {len(func_names)} functions",
            )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="Function verification failed",
                details=f"{type(e).__name__}: {e}",
            )

    def verify_seed_data(self, conn: psycopg.Connection) -> SetupResult:
        """Verify that seed data was applied."""
        try:
            result = conn.execute("SELECT COUNT(*) as count FROM fraud_gov.rule_fields").fetchone()

            count = result["count"] if result else 0

            if count < 6:  # We expect at least 6 core fields
                return SetupResult(
                    success=False,
                    message="Seed data verification failed",
                    details=f"Expected at least 6 rule fields, found {count}",
                )

            return SetupResult(
                success=True,
                message="Seed data verified",
                details=f"Found {count} rule fields",
            )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="Seed data verification failed",
                details=f"{type(e).__name__}: {e}",
            )

    def test_app_connection(self) -> SetupResult:
        """Test that app user can connect."""
        if not self.app_url:
            return SetupResult(
                success=True,
                message="App connection test skipped",
                details="DATABASE_URL_APP not set",
            )

        try:
            with psycopg.connect(self.app_url, autocommit=True) as conn:
                result = conn.execute("SELECT current_user, current_database()").fetchone()
                return SetupResult(
                    success=True,
                    message="App connection successful",
                    details=f"User: {result['current_user']}, DB: {result['current_database']}",
                )
        except psycopg.Error as e:
            return SetupResult(
                success=False,
                message="App connection failed",
                details=f"{type(e).__name__}: {e}",
            )

    def init(self, demo: bool = False) -> int:
        """Run first-time setup: create users, schema, indexes, seed data."""
        total_steps = 7
        results = []

        log_step(1, total_steps, "Connecting to database (admin)")
        try:
            with psycopg.connect(self.admin_url, autocommit=False, row_factory=dict_row) as conn:
                # Test connection
                result = conn.execute("SELECT version()").fetchone()
                log_success(f"Connected to: {result['version'].split(',')[0]}")

                # Step 2: Create users
                log_step(2, total_steps, "Creating database users")
                if self.app_password and self.analytics_password:
                    user_result = self.create_users(conn)
                    results.append(user_result)
                    if user_result.success:
                        log_success(f"{user_result.message}: {user_result.details}")
                    else:
                        log_error(f"{user_result.message}: {user_result.details}")
                        return 1
                else:
                    log_warning("Skipping user creation (passwords not provided)")

                # Step 3: Verify users exist
                log_step(3, total_steps, "Verifying database users")
                user_check = self.verify_users(conn)
                results.append(user_check)
                if user_check.success:
                    log_success(f"{user_check.message}: {user_check.details}")
                else:
                    log_error(f"{user_check.message}: {user_check.details}")
                    return 1

                # Step 4: Create schema
                log_step(4, total_steps, "Creating schema (fraud_governance_schema.sql)")
                schema_sql = self._load_sql_file("fraud_governance_schema.sql")
                schema_result = self._execute_sql(conn, schema_sql, "Schema creation")
                results.append(schema_result)
                if schema_result.success:
                    log_success(f"{schema_result.message}: {schema_result.details}")
                else:
                    log_error(f"{schema_result.message}: {schema_result.details}")
                    return 1

                # Step 5: Apply production indexes
                log_step(5, total_steps, "Creating production indexes (production_indexes.sql)")
                try:
                    indexes_sql = self._load_sql_file("production_indexes.sql")
                    index_result = self._execute_sql(conn, indexes_sql, "Index creation")
                    results.append(index_result)
                    if index_result.success:
                        log_success(f"{index_result.message}: {index_result.details}")
                    else:
                        log_warning(f"{index_result.message}: {index_result.details}")
                except FileNotFoundError:
                    log_warning("production_indexes.sql not found, skipping")

                # Step 6: Apply seed data
                log_step(6, total_steps, "Applying seed data (seed_rule_fields.sql)")
                seed_sql = self._load_sql_file("seed_rule_fields.sql")
                seed_result = self._execute_sql(conn, seed_sql, "Seed data application")
                results.append(seed_result)
                if seed_result.success:
                    log_success(f"{seed_result.message}: {seed_result.details}")
                else:
                    log_error(f"{seed_result.message}: {seed_result.details}")
                    return 1

                # Step 7: Optionally apply demo data
                if demo:
                    log_info("Applying demo data...")
                    try:
                        demo_sql = self._load_sql_file("seed_demo_data.sql")
                        demo_result = self._execute_sql(conn, demo_sql, "Demo data application")
                        results.append(demo_result)
                        if demo_result.success:
                            log_success(f"{demo_result.message}: {demo_result.details}")
                        else:
                            log_warning(f"{demo_result.message}: {demo_result.details}")
                    except FileNotFoundError:
                        log_warning("seed_demo_data.sql not found, skipping")

        except psycopg.Error as e:
            log_error(f"Database connection failed: {type(e).__name__}: {e}")
            return 1

        # Verification
        log_step(8 if demo else 7, total_steps, "Final verification")
        self._run_verification()

        return self._print_summary(results)

    def reset(self, mode: ResetMode, force: bool = False) -> int:
        """Reset database."""
        # Safety check for production
        if not force and "prod" in self.admin_url.lower():
            response = input("Resetting PRODUCTION database! Type 'YES' to confirm: ")
            if response != "YES":
                log_info("Reset cancelled.")
                return 0

        total_steps = 5 if mode == ResetMode.SCHEMA else 3
        results = []

        log_step(1, total_steps, f"Resetting database (mode: {mode.value})")

        try:
            with psycopg.connect(self.admin_url, autocommit=False, row_factory=dict_row) as conn:
                if mode == ResetMode.SCHEMA:
                    # Drop and recreate schema
                    log_step(2, total_steps, "Dropping schema...")
                    conn.execute("DROP SCHEMA IF EXISTS fraud_gov CASCADE;")
                    conn.commit()
                    log_success("Schema dropped")

                    log_step(3, total_steps, "Recreating schema...")
                    schema_sql = self._load_sql_file("fraud_governance_schema.sql")
                    result = self._execute_sql(conn, schema_sql, "Schema creation")
                    results.append(result)
                    if result.success:
                        log_success(f"{result.message}: {result.details}")
                    else:
                        log_error(f"{result.message}: {result.details}")
                        return 1

                    log_step(4, total_steps, "Applying indexes...")
                    try:
                        indexes_sql = self._load_sql_file("production_indexes.sql")
                        result = self._execute_sql(conn, indexes_sql, "Index creation")
                        results.append(result)
                        if result.success:
                            log_success(f"{result.message}: {result.details}")
                    except FileNotFoundError:
                        log_warning("production_indexes.sql not found")

                    step_num = 5
                else:
                    # Data mode: truncate tables
                    log_step(2, total_steps, "Truncating tables...")
                    truncate_order = [
                        "fraud_gov.audit_log",
                        "fraud_gov.approvals",
                        "fraud_gov.ruleset_version_rules",
                        "fraud_gov.ruleset_versions",
                        "fraud_gov.ruleset_manifest",
                        "fraud_gov.rulesets",
                        "fraud_gov.rule_versions",
                        "fraud_gov.rules",
                        "fraud_gov.rule_field_versions",
                        "fraud_gov.field_registry_manifest",
                        "fraud_gov.rule_fields",
                        "fraud_gov.rule_field_metadata",
                    ]
                    for table in truncate_order:
                        conn.execute(f"TRUNCATE TABLE {table} CASCADE;")
                    conn.commit()
                    log_success(f"Truncated {len(truncate_order)} tables")
                    step_num = 3

                # Reseed data
                log_step(step_num, total_steps, "Reseeding data...")
                seed_sql = self._load_sql_file("seed_rule_fields.sql")
                result = self._execute_sql(conn, seed_sql, "Seed data application")
                results.append(result)
                if result.success:
                    log_success(f"{result.message}: {result.details}")

        except psycopg.Error as e:
            log_error(f"Database reset failed: {type(e).__name__}: {e}")
            return 1

        log_success("Database reset complete!")
        return 0

    def seed(self, demo: bool = False, clean_first: bool = False) -> int:
        """Apply seed data."""
        try:
            with psycopg.connect(self.admin_url, autocommit=False) as conn:
                if clean_first:
                    log_info("Cleaning existing data first...")
                    truncate_order = [
                        "fraud_gov.audit_log",
                        "fraud_gov.approvals",
                        "fraud_gov.ruleset_version_rules",
                        "fraud_gov.ruleset_versions",
                        "fraud_gov.ruleset_manifest",
                        "fraud_gov.rulesets",
                        "fraud_gov.rule_versions",
                        "fraud_gov.rules",
                        "fraud_gov.rule_field_versions",
                        "fraud_gov.field_registry_manifest",
                        "fraud_gov.rule_fields",
                        "fraud_gov.rule_field_metadata",
                    ]
                    for table in truncate_order:
                        conn.execute(f"TRUNCATE TABLE {table} CASCADE;")
                    conn.commit()
                    log_success("Cleaned existing data")

                log_info("Applying seed data...")
                seed_sql = self._load_sql_file("seed_rule_fields.sql")
                result = self._execute_sql(conn, seed_sql, "Seed data application")
                if result.success:
                    log_success(f"{result.message}: {result.details}")
                else:
                    log_error(f"{result.message}: {result.details}")
                    return 1

                if demo:
                    log_info("Applying demo data...")
                    try:
                        demo_sql = self._load_sql_file("seed_demo_data.sql")
                        result = self._execute_sql(conn, demo_sql, "Demo data application")
                        if result.success:
                            log_success(f"{result.message}: {result.details}")
                        else:
                            log_warning(f"{result.message}: {result.details}")
                    except FileNotFoundError:
                        log_warning("seed_demo_data.sql not found, skipping")

        except psycopg.Error as e:
            log_error(f"Seed failed: {type(e).__name__}: {e}")
            return 1

        return 0

    def verify(self) -> int:
        """Verify database setup."""
        self._run_verification()
        return 0

    def create_users_command(self) -> int:
        """Create users only (standalone command)."""
        try:
            with psycopg.connect(self.admin_url, autocommit=False) as conn:
                result = self.create_users(conn)
                if result.success:
                    log_success(f"{result.message}: {result.details}")
                    return 0
                else:
                    log_error(f"{result.message}: {result.details}")
                    return 1
        except psycopg.Error as e:
            log_error(f"Failed to create users: {type(e).__name__}: {e}")
            return 1

    def _run_verification(self) -> None:
        """Run verification checks."""
        try:
            with psycopg.connect(self.admin_url, autocommit=False, row_factory=dict_row) as conn:
                checks = [
                    ("Users", self.verify_users(conn)),
                    ("Schema", self.verify_schema(conn)),
                    ("Indexes", self.verify_indexes(conn)),
                    ("Triggers", self.verify_triggers(conn)),
                    ("Functions", self.verify_functions(conn)),
                    ("Seed data", self.verify_seed_data(conn)),
                ]

                for name, result in checks:
                    if result.success:
                        log_success(f"{name}: {result.details}")
                    else:
                        log_warning(f"{name}: {result.details}")

        except psycopg.Error as e:
            log_error(f"Verification failed: {type(e).__name__}: {e}")

    def _print_summary(self, results: list[SetupResult]) -> int:
        """Print summary of results."""
        print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
        print(f"{Colors.BOLD}SETUP SUMMARY{Colors.END}")
        print(f"{Colors.BOLD}{'=' * 60}{Colors.END}")

        for r in results:
            status = (
                f"{Colors.GREEN}[OK]{Colors.END}"
                if r.success
                else f"{Colors.RED}[FAIL]{Colors.END}"
            )
            print(f"{status} {r.message}")

        failed = [r for r in results if not r.success]
        if failed:
            log_warning(f"\n{len(failed)} step(s) had warnings or failures.")
            return 1

        log_success("\nDatabase setup completed successfully!")
        return 0


def get_passwords_from_env() -> tuple[str | None, str | None]:
    """Get passwords from environment variables (Doppler injected)."""
    app_pass = os.getenv("FRAUD_GOV_APP_PASSWORD")
    analytics_pass = os.getenv("FRAUD_GOV_ANALYTICS_PASSWORD")
    return app_pass, analytics_pass


def prompt_for_passwords() -> tuple[str, str]:
    """Securely prompt for user passwords (no echo)."""
    print("\nCreate database users")
    print("=" * 40)

    app_pass = getpass.getpass("Password for fraud_gov_app_user: ")
    app_pass_confirm = getpass.getpass("Confirm password: ")
    if app_pass != app_pass_confirm:
        raise ValueError("Passwords do not match")

    analytics_pass = getpass.getpass("Password for fraud_gov_analytics_user: ")
    analytics_pass_confirm = getpass.getpass("Confirm password: ")
    if analytics_pass != analytics_pass_confirm:
        raise ValueError("Passwords do not match")

    return app_pass, analytics_pass


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Automated database setup for Fraud Governance API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--admin-url",
        help="Admin database URL (overrides env var)",
    )
    parser.add_argument(
        "--app-url",
        help="App database URL (overrides env var)",
    )
    parser.add_argument(
        "--password-env",
        action="store_true",
        help="Read passwords from FRAUD_GOV_APP_PASSWORD and FRAUD_GOV_ANALYTICS_PASSWORD env vars",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompts",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init command
    init_parser = subparsers.add_parser("init", help="First-time setup")
    init_parser.add_argument("--demo", action="store_true", help="Include demo data")

    # reset command
    reset_parser = subparsers.add_parser("reset", help="Reset database")
    reset_parser.add_argument(
        "--mode",
        choices=["schema", "data"],
        default="schema",
        help="Reset mode: schema (drop/recreate) or data (truncate only)",
    )
    reset_parser.add_argument(
        "--force",
        "--yes",
        "-y",
        dest="force",
        action="store_true",
        help="Bypass safety checks (--yes or -y also accepted)",
    )

    # seed command
    seed_parser = subparsers.add_parser("seed", help="Apply seed data")
    seed_parser.add_argument("--demo", action="store_true", help="Include demo data")
    seed_parser.add_argument(
        "--clean-first", action="store_true", help="Truncate tables before seeding"
    )

    # verify command
    subparsers.add_parser("verify", help="Verify database setup")

    # create-users command
    subparsers.add_parser("create-users", help="Create database users only")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Get database URLs
    admin_url = args.admin_url or os.getenv("DATABASE_URL_ADMIN")
    app_url = args.app_url or os.getenv("DATABASE_URL_APP")

    if not admin_url:
        log_error("DATABASE_URL_ADMIN is required")
        log_info("Set it as environment variable or via --admin-url")
        return 2

    # Get passwords
    app_password = None
    analytics_password = None

    if args.password_env:
        app_password, analytics_password = get_passwords_from_env()
        if not app_password or not analytics_password:
            log_error(
                "FRAUD_GOV_APP_PASSWORD and FRAUD_GOV_ANALYTICS_PASSWORD must be set when using --password-env"
            )
            return 2
    elif args.command in ("init", "create-users"):
        try:
            app_password, analytics_password = prompt_for_passwords()
        except ValueError as e:
            log_error(str(e))
            return 2

    # Create setup instance
    setup = DatabaseSetup(
        admin_url=admin_url,
        app_url=app_url,
        app_password=app_password,
        analytics_password=analytics_password,
    )

    # Execute command
    if args.command == "init":
        return setup.init(demo=args.demo)
    elif args.command == "reset":
        return setup.reset(mode=ResetMode(args.mode), force=args.force)
    elif args.command == "seed":
        return setup.seed(demo=args.demo, clean_first=args.clean_first)
    elif args.command == "verify":
        return setup.verify()
    elif args.command == "create-users":
        return setup.create_users_command()

    return 0


if __name__ == "__main__":
    sys.exit(main())
