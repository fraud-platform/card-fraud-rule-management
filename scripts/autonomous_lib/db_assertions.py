"""
Database assertion evaluator for autonomous testing.

Provides DB connection pooling and query evaluation for:
- skip_if conditions (state-aware step skipping)
- db_assert validations (post-execution state verification)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from scripts.autonomous_lib.scenario import ExecutionContext

try:
    import psycopg
    from psycopg.rows import dict_row

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False


@dataclass
class DbAssertionResult:
    """Result of a DB assertion evaluation."""

    passed: bool
    actual_value: Any = None
    expected_value: Any = None
    error_message: str = ""


class DbConnectionManager:
    """Manages database connections for autonomous testing.

    Uses psycopg3 to connect to PostgreSQL and execute queries.
    Connection details are sourced from environment variables.
    """

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.environ.get("DATABASE_URL_APP", "")
        self._conn = None

    def connect(self) -> bool:
        """Establish a database connection.

        Returns True if connection successful, False otherwise.
        """
        if not PSYCOPG_AVAILABLE:
            return False

        if not self.database_url:
            return False

        try:
            # Parse connection string
            parsed = urlparse(self.database_url)
            self._conn = psycopg.connect(
                host=parsed.hostname or "localhost",
                port=parsed.port or 5432,
                user=parsed.username or "postgres",
                password=parsed.password or "",
                dbname=parsed.path.lstrip("/") if parsed.path else "fraud_gov",
                row_factory=dict_row,
            )
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return results.

        Args:
            query: SQL query string (may use :param placeholders)
            params: Dictionary of parameter values

        Returns:
            List of result rows as dictionaries
        """
        if not self._conn:
            return []

        try:
            cursor = self._conn.cursor()

            # Convert :param placeholders to %(param)s format for psycopg
            postgres_query = query
            if params:
                for key in params:
                    postgres_query = postgres_query.replace(f":{key}", f"%({key})s")

            cursor.execute(postgres_query, params)
            return cursor.fetchall()
        except Exception:
            return []

    def execute_query_one(
        self, query: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute a query and return the first result.

        Args:
            query: SQL query string (may use :param placeholders)
            params: Dictionary of parameter values

        Returns:
            First result row as dictionary, or None if no results
        """
        results = self.execute_query(query, params)
        return results[0] if results else None

    def get_table_count(self, table_name: str, schema: str = "fraud_gov") -> int:
        """Get the row count for a table."""
        result = self.execute_query_one(f"SELECT COUNT(*) as count FROM {schema}.{table_name}")
        return result["count"] if result else 0


class DbAssertionEvaluator:
    """Evaluates database assertions for scenario validation."""

    def __init__(self, db_manager: DbConnectionManager | None = None):
        self.db_manager = db_manager or DbConnectionManager()
        self._connected = False

    def connect(self) -> bool:
        """Establish database connection if not already connected."""
        if self._connected:
            return True
        self._connected = self.db_manager.connect()
        return self._connected

    def close(self) -> None:
        """Close database connection."""
        self.db_manager.close()
        self._connected = False

    def evaluate_skip_condition(
        self,
        db_query: str,
        condition: str,
        context_vars: dict[str, Any],
    ) -> tuple[bool, str]:
        """Evaluate a skip_if condition.

        Args:
            db_query: SQL query to execute (may use :param placeholders from context)
            condition: Condition expression to evaluate (e.g., "status NOT IN ('DRAFT', 'REJECTED')")
            context_vars: Variables to substitute into query

        Returns:
            (should_skip, reason)
        """
        if not self.connect():
            return False, "DB not available"

        # Execute query
        result = self.db_manager.execute_query_one(db_query, context_vars)
        if not result:
            return False, "No result from query"

        # Evaluate condition against result
        # This is a simple implementation that handles common cases
        should_skip, reason = self._evaluate_condition(result, condition)
        return should_skip, reason

    def _evaluate_condition(
        self,
        row: dict[str, Any],
        condition: str,
    ) -> tuple[bool, str]:
        """Evaluate a condition string against a database row.

        Supports simple conditions:
        - status = 'APPROVED'
        - status NOT IN ('DRAFT', 'REJECTED')
        - status = 'ACTIVE'
        - count > 0
        """
        try:
            # Extract the column name and expected values
            condition_upper = condition.upper()

            # Handle "NOT IN" conditions
            if " NOT IN " in condition_upper:
                parts = condition.split(" NOT IN ", 1)
                col = parts[0].strip()
                values_str = parts[1].strip().strip("()")
                expected_values = [v.strip().strip("'\"") for v in values_str.split(",")]
                actual_value = row.get(col)
                should_skip = actual_value not in expected_values
                return should_skip, f"{col}={actual_value} not in {expected_values}"

            # Handle "IN" conditions
            if " IN " in condition_upper:
                parts = condition.split(" IN ", 1)
                col = parts[0].strip()
                values_str = parts[1].strip().strip("()")
                expected_values = [v.strip().strip("'\"") for v in values_str.split(",")]
                actual_value = row.get(col)
                should_skip = actual_value in expected_values
                return should_skip, f"{col}={actual_value} in {expected_values}"

            # Handle equality conditions
            if " = " in condition:
                parts = condition.split(" = ", 1)
                col = parts[0].strip()
                expected = parts[1].strip().strip("'\"")
                actual_value = row.get(col)
                should_skip = str(actual_value) == expected
                return should_skip, f"{col}={actual_value} equals {expected}"

            # Handle inequality conditions
            if " > " in condition:
                parts = condition.split(" > ", 1)
                col = parts[0].strip()
                expected = float(parts[1].strip())
                actual_value = row.get(col)
                should_skip = float(actual_value) > expected if actual_value is not None else False
                return should_skip, f"{col}={actual_value} > {expected}"

            # Handle < conditions
            if " < " in condition:
                parts = condition.split(" < ", 1)
                col = parts[0].strip()
                expected = float(parts[1].strip())
                actual_value = row.get(col)
                should_skip = float(actual_value) < expected if actual_value is not None else False
                return should_skip, f"{col}={actual_value} < {expected}"

            # Default: don't skip
            return False, f"Could not evaluate condition: {condition}"

        except Exception:
            return False, f"Error evaluating condition: {condition}"

    def evaluate_assertion(
        self,
        query: str,
        expect: str | int | list[Any] | None = None,
        expect_row_count: int | None = None,
        expect_empty: bool = False,
        params: dict[str, Any] | None = None,
    ) -> DbAssertionResult:
        """Evaluate a database assertion.

        Args:
            query: SQL query to execute
            expect: Expected value (for single-value queries)
            expect_row_count: Expected number of rows returned
            expect_empty: Whether result should be empty
            params: Query parameters

        Returns:
            DbAssertionResult with evaluation outcome
        """
        if not self.connect():
            return DbAssertionResult(passed=False, error_message="DB not available")

        try:
            # Execute query
            results = self.db_manager.execute_query(query, params)

            # Check row count expectation
            if expect_row_count is not None:
                actual_count = len(results)
                return DbAssertionResult(
                    passed=actual_count == expect_row_count,
                    actual_value=actual_count,
                    expected_value=expect_row_count,
                    error_message=""
                    if actual_count == expect_row_count
                    else f"Expected {expect_row_count} rows, got {actual_count}",
                )

            # Check empty expectation
            if expect_empty:
                return DbAssertionResult(
                    passed=len(results) == 0,
                    actual_value=len(results),
                    expected_value=0,
                    error_message=""
                    if len(results) == 0
                    else f"Expected empty result, got {len(results)} rows",
                )

            # Check single value expectation
            if expect is not None:
                if results:
                    # Get first value from first row
                    first_row = results[0]
                    first_value = next(iter(first_row.values())) if first_row else None

                    # Handle different types of expected values
                    if isinstance(expect, list):
                        passed = first_value in expect
                    else:
                        passed = str(first_value) == str(expect)

                    return DbAssertionResult(
                        passed=passed,
                        actual_value=first_value,
                        expected_value=expect,
                        error_message="" if passed else f"Expected {expect}, got {first_value}",
                    )
                else:
                    return DbAssertionResult(
                        passed=False,
                        expected_value=expect,
                        error_message=f"Expected {expect}, but query returned no results",
                    )

            # No specific expectation - just check query succeeded
            return DbAssertionResult(
                passed=True,
                actual_value=len(results),
            )

        except Exception as e:
            return DbAssertionResult(passed=False, error_message=str(e))


class SkipConditionEvaluator:
    """Evaluates skip conditions for scenario steps."""

    def __init__(self, db_evaluator: DbAssertionEvaluator | None = None):
        self.db_evaluator = db_evaluator or DbAssertionEvaluator()

    def should_skip(
        self,
        skip_condition,
        context: ExecutionContext,
    ) -> tuple[bool, str]:
        """Evaluate if a step should be skipped.

        Args:
            skip_condition: SkipCondition object from scenario
            context: ExecutionContext with variables

        Returns:
            (should_skip, reason)
        """
        # DB-based skip condition
        if skip_condition.db_query and skip_condition.db_condition:
            should_skip, reason = self.db_evaluator.evaluate_skip_condition(
                skip_condition.db_query,
                skip_condition.db_condition,
                context.variables,
            )
            if should_skip:
                return True, reason

        # Variable existence check
        if skip_condition.variable_exists:
            exists = skip_condition.variable_exists in context.variables
            if exists:
                return True, f"Variable {skip_condition.variable_exists} exists"

        # Variable equality check
        if skip_condition.variable_equals:
            for key, expected in skip_condition.variable_equals.items():
                actual = context.get_variable(key)
                if str(actual) == str(expected):
                    return True, f"Variable {key} equals {expected}"

        return False, ""


def create_db_evaluator() -> DbAssertionEvaluator:
    """Factory function to create a DB assertion evaluator.

    Attempts to connect to the database using environment variables.
    Returns an evaluator that may not be connected (call connect() to connect).
    """
    manager = DbConnectionManager()
    return DbAssertionEvaluator(manager)
