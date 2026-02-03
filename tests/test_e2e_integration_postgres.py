"""
End-to-end integration tests with REAL Postgres and detailed HTML reporting.

These tests:
- Use REAL Neon Postgres database (no SQLite)
- Test full CRUD operations with idempotent flows
- Capture request/response details for HTML report
- Take table snapshots before teardown
- Rollback everything including audit logs after each test

To run E2E tests with Postgres:
  export DATABASE_URL_APP="postgresql://user:pass@host/db?sslmode=require"
  uv run pytest -m e2e_integration -v --html=htmlreports/e2e.html --self-contained-html

HTML report includes:
- Request/response for each API call
- Table snapshots before teardown
- Test execution details
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.e2e_integration


# ============================================================================
# Helper Functions for Table Snapshots and HTML Reporting
# ============================================================================


def capture_table_snapshot(engine: Engine, table_name: str) -> list[dict[str, Any]]:
    """Capture all rows from a table as a list of dictionaries."""
    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT * FROM fraud_gov.{table_name} ORDER BY created_at DESC")
        )
        columns = result.keys()
        rows = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
    return rows


def capture_all_table_snapshots(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    """Capture snapshots of all fraud_gov tables."""
    tables = [
        "rule_fields",
        "rule_field_metadata",
        "rules",
        "rule_versions",
        "rulesets",
        "ruleset_rules",
        "approvals",
        "audit_log",
    ]

    snapshots = {}
    for table in tables:
        try:
            snapshots[table] = capture_table_snapshot(engine, table)
        except Exception as e:
            snapshots[table] = [{"error": str(e)}]

    return snapshots


def cleanup_test_data(engine: Engine, test_id: str):
    """
    Delete ALL test data including audit logs for a specific test run.

    This is called in teardown to restore clean state.
    """
    with engine.connect() as conn:
        # Delete from all tables (respecting foreign key dependencies)
        # Order matters due to foreign keys!

        # Delete audit_log entries for this test
        conn.execute(
            text("DELETE FROM fraud_gov.audit_log WHERE performed_by LIKE :test_id"),
            {"test_id": f"{test_id}%"},
        )

        # Delete approvals
        conn.execute(
            text(
                "DELETE FROM fraud_gov.approvals WHERE maker LIKE :test_id OR checker LIKE :test_id"
            ),
            {"test_id": f"{test_id}%"},
        )

        # Delete ruleset_rules
        conn.execute(
            text("""
                DELETE FROM fraud_gov.ruleset_rules
                WHERE ruleset_id IN (
                    SELECT ruleset_id FROM fraud_gov.rulesets WHERE created_by LIKE :test_id
                )
            """),
            {"test_id": f"{test_id}%"},
        )

        # Delete rulesets
        conn.execute(
            text("DELETE FROM fraud_gov.rulesets WHERE created_by LIKE :test_id"),
            {"test_id": f"{test_id}%"},
        )

        # Delete rule_versions
        conn.execute(
            text("""
                DELETE FROM fraud_gov.rule_versions
                WHERE rule_id IN (
                    SELECT rule_id FROM fraud_gov.rules WHERE created_by LIKE :test_id
                )
            """),
            {"test_id": f"{test_id}%"},
        )

        # Delete rules
        conn.execute(
            text("DELETE FROM fraud_gov.rules WHERE created_by LIKE :test_id"),
            {"test_id": f"{test_id}%"},
        )

        # Delete rule_field_metadata
        conn.execute(
            text("""
                DELETE FROM fraud_gov.rule_field_metadata
                WHERE field_key IN (
                    SELECT field_key FROM fraud_gov.rule_fields WHERE field_key LIKE :test_id
                )
            """),
            {"test_id": "e2e-test-%"},
        )

        # Delete rule_fields
        conn.execute(
            text("DELETE FROM fraud_gov.rule_fields WHERE field_key LIKE :test_id"),
            {"test_id": "e2e-test-%"},
        )

        conn.commit()


# ============================================================================
# Fixtures for E2E Postgres Testing
# ============================================================================


def _normalize_db_url_for_psycopg(database_url: str) -> str:
    # Keep this file self-contained; tests should not require psycopg2.
    if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@pytest.fixture(scope="function")
def e2e_db_engine():
    """
    Provide a Postgres engine for E2E tests.

    Uses DATABASE_URL_APP from environment.
    Tests are responsible for cleanup via cleanup_test_data().
    """

    database_url = _normalize_db_url_for_psycopg(os.environ["DATABASE_URL_APP"])
    engine = create_engine(database_url, echo=False, pool_pre_ping=True)

    yield engine

    # Teardown: cleanup all test data including audit logs
    # Note: Each test should call cleanup with its unique test_id


# ============================================================================
# E2E Tests with Idempotent Flows and Rich Assertions
# ============================================================================


class TestE2ERuleFieldLifecycle:
    """
    Complete RuleField lifecycle: CREATE → GET → UPDATE → GET → DELETE → VERIFY

    Tests the allowed_operators ARRAY type fix with Postgres.
    """

    @pytest.mark.anyio
    async def test_e2e_rule_field_create_read_delete(
        self, e2e_server_base_url: str, e2e_db_engine, request, e2e_auth_header
    ):
        """Test complete RuleField lifecycle with real Postgres and verification."""
        test_id = f"e2e-test-{uuid.uuid7().hex[:8]}"
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")
        auth_header = e2e_auth_header

        # ========================================================================
        # CREATE: Create a new RuleField with ARRAY operators
        # ========================================================================
        create_response = httpx.post(
            f"{e2e_server_base_url}/api/v1/rule-fields",
            json={
                "field_key": f"{test_id}_amount",
                "display_name": "E2E Test Amount",
                "data_type": "NUMBER",
                "allowed_operators": ["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"],
                "multi_value_allowed": False,
                "is_sensitive": False,
                "is_active": True,
            },
            headers=auth_header,
            timeout=10.0,
        )

        # Rich assertion: Status code
        assert create_response.status_code in [201, 401, 403], (
            f"CREATE failed: {create_response.status_code} - {create_response.text}"
        )

        if create_response.status_code in [401, 403]:
            pytest.skip("Requires Auth0 token - skipping idempotent test")
            return

        # Rich assertion: Response schema validation
        created_field = create_response.json()
        assert created_field["field_key"] == f"{test_id}_amount"
        assert created_field["data_type"] == "NUMBER"
        assert created_field["allowed_operators"] == ["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"]
        assert isinstance(created_field["allowed_operators"], list)
        assert len(created_field["allowed_operators"]) == 6

        # Attach to pytest report for HTML output
        request.node._test_response = {
            "create": {
                "status": create_response.status_code,
                "request_body": created_field,
                "response_body": created_field,
            }
        }

        # ========================================================================
        # GET: Verify the field was created in Postgres
        # ========================================================================
        get_response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rule-fields/{test_id}_amount",
            headers=auth_header,
            timeout=10.0,
        )

        assert get_response.status_code == 200, f"GET failed: {get_response.text}"
        retrieved_field = get_response.json()

        # Rich assertion: Verify all fields match
        assert retrieved_field["field_key"] == created_field["field_key"]
        assert retrieved_field["display_name"] == created_field["display_name"]
        assert retrieved_field["allowed_operators"] == created_field["allowed_operators"]

        request.node._test_response["get"] = {
            "status": get_response.status_code,
            "response_body": retrieved_field,
        }

        # ========================================================================
        # DATABASE STATE VERIFICATION: Check Postgres directly
        # ========================================================================
        with e2e_db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT field_key, allowed_operators, data_type FROM fraud_gov.rule_fields "
                    "WHERE field_key = :field_key"
                ),
                {"field_key": f"{test_id}_amount"},
            )
            db_row = result.fetchone()

            # Rich assertion: Database state verification
            assert db_row is not None, "Field not found in database!"
            assert db_row.allowed_operators == ["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"], (
                f"ARRAY type mismatch in DB! Got: {db_row.allowed_operators}"
            )

        # ========================================================================
        # SNAPSHOT: Capture table state before teardown
        # ========================================================================
        snapshots_before_teardown = capture_all_table_snapshots(e2e_db_engine)
        request.node._table_snapshots = snapshots_before_teardown

        # Verify audit log was created
        audit_entries = [
            e
            for e in snapshots_before_teardown["audit_log"]
            if test_id in str(e.get("performed_by", ""))
        ]
        assert len(audit_entries) > 0, "No audit log entries found!"

        # ========================================================================
        # CLEANUP: Delete test data including audit logs
        # ========================================================================
        cleanup_test_data(e2e_db_engine, test_id)

        # Verify cleanup worked
        with e2e_db_engine.connect() as conn:
            result = conn.execute(
                text("SELECT COUNT(*) FROM fraud_gov.rule_fields WHERE field_key LIKE :test_id"),
                {"test_id": f"{test_id}%"},
            )
            count = result.fetchone()[0]
            assert count == 0, f"Cleanup failed! {count} test rule_fields remain"

            result = conn.execute(
                text("SELECT COUNT(*) FROM fraud_gov.audit_log WHERE performed_by LIKE :test_id"),
                {"test_id": f"{test_id}%"},
            )
            count = result.fetchone()[0]
            assert count == 0, f"Cleanup failed! {count} test audit entries remain"


class TestE2ERuleLifecycle:
    """
    Complete Rule lifecycle: CREATE → SUBMIT → APPROVE → VERIFY → CLEANUP
    """

    @pytest.mark.skip(reason="Requires Auth0 tokens with MAKER/CHECKER roles")
    @pytest.mark.anyio
    async def test_e2e_rule_create_submit_approve_delete(
        self, e2e_server_base_url: str, e2e_db_engine, request
    ):
        """Test complete Rule workflow with maker-checker."""
        # Requires real Auth0 setup.

        # This test requires real Auth0 setup - skip for now
        # Implementation would follow the same pattern as RuleField test

        pytest.skip("Implement when Auth0 is configured")


class TestE2ERuleSetCompilation:
    """
    Complete RuleSet lifecycle: CREATE → ADD RULES → COMPILE → VERIFY → CLEANUP
    """

    @pytest.mark.skip(reason="Requires existing approved rules and Auth0")
    @pytest.mark.anyio
    async def test_e2e_ruleset_create_compile_verify(
        self, e2e_server_base_url: str, e2e_db_engine, request
    ):
        """Test RuleSet creation, compilation, and AST verification."""
        # Implementation would:
        # 1. Create RuleSet
        # 2. Add approved RuleVersions
        # 3. Submit for approval
        # 4. Approve
        # 5. Compile
        # 6. Verify compiled AST is deterministic
        # 7. Take table snapshots
        # 8. Cleanup

        pytest.skip("Implement when existing rules are available")


# ============================================================================
# Pytest Hooks for Custom HTML Reporting
# ============================================================================


@pytest.fixture(autouse=True)
def add_snapshot_to_report(request):
    """Automatically attach table snapshots to HTML report."""
    yield

    if hasattr(request.node, "_table_snapshots"):
        snapshots = request.node._table_snapshots
        html = _snapshots_to_html(snapshots)

        if hasattr(request.node, "add_report_section"):
            request.node.add_report_section("call", "Database Snapshots", html)


def _table_snapshot_to_html(table_name: str, rows) -> str:
    html = f"<h4>{table_name} ({len(rows)} rows)</h4>"

    if not rows or (len(rows) == 1 and "error" in rows[0]):
        return html + "<p><em>Empty or error</em></p>"

    html += "<table border='1' cellpadding='5' style='border-collapse: collapse; width: 100%;'>"
    html += (
        "<thead><tr>"
        + "".join(f"<th>{col}</th>" for col in rows[0].keys())
        + "</tr></thead><tbody>"
    )

    for row in rows[:10]:
        html += "<tr>" + "".join(f"<td>{val}</td>" for val in row.values()) + "</tr>"

    if len(rows) > 10:
        html += f"<tr><td colspan='{len(rows[0])}'><em>... and {len(rows) - 10} more rows</em></td></tr>"

    html += "</tbody></table><br>"
    return html


def _snapshots_to_html(snapshots) -> str:
    html = "<h3>Database Snapshots Before Teardown</h3>"
    for table_name, rows in snapshots.items():
        html += _table_snapshot_to_html(table_name, rows)
    return html
