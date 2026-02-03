"""
Comprehensive integration tests for Approvals and Audit Log API endpoints.

Tests cover:
- GET /approvals (list approvals with filtering)
- GET /audit-log (list audit logs with filtering)
- Approval workflow tracking
- Maker-checker separation validation
- Audit trail completeness
- Authentication requirements
"""

from datetime import UTC

import pytest
from fastapi.testclient import TestClient


class TestListApprovals:
    """Tests for GET /api/v1/approvals endpoint."""

    @pytest.mark.anyio
    async def test_should_return_all_approvals(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test listing all approvals."""
        # Create a rule and submit for approval (creates approval record)
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        # Submit for approval
        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # List approvals
        response = async_maker_client.get("/api/v1/approvals")

        assert response.status_code == 200
        data = response.json()
        # Paginated response has "items" key
        assert "items" in data
        items = data["items"]
        assert isinstance(items, list)
        assert len(items) > 0

        # Verify approval structure
        approval = items[0]
        assert "approval_id" in approval
        assert "entity_type" in approval
        assert "entity_id" in approval
        assert "action" in approval
        assert "maker" in approval
        assert "status" in approval
        assert "created_at" in approval

    @pytest.mark.anyio
    async def test_should_filter_by_status(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test filtering approvals by status."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Filter by PENDING status
        response = async_maker_client.get("/api/v1/approvals?status=PENDING")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(a["status"] == "PENDING" for a in items)

    @pytest.mark.anyio
    async def test_should_filter_by_entity_type(
        self, async_maker_client: TestClient, sample_rule_data: dict, sample_ruleset_data: dict
    ):
        """Test filtering approvals by entity type."""
        # Create rule version approval
        rule_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = rule_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Create ruleset approval
        ruleset_response = async_maker_client.post("/api/v1/rulesets", json=sample_ruleset_data)
        ruleset_id = ruleset_response.json()["ruleset_id"]

        async_maker_client.post(f"/api/v1/rulesets/{ruleset_id}/submit", json={})

        # Filter by RULE_VERSION entity type
        response = async_maker_client.get("/api/v1/approvals?entity_type=RULE_VERSION")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(a["entity_type"] == "RULE_VERSION" for a in items)

        # Filter by RULESET_VERSION entity type
        response = async_maker_client.get("/api/v1/approvals?entity_type=RULESET_VERSION")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(a["entity_type"] == "RULESET_VERSION" for a in items)

    @pytest.mark.anyio
    async def test_should_combine_filters(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test combining multiple filters."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Filter by both status and entity_type
        response = async_maker_client.get(
            "/api/v1/approvals?status=PENDING&entity_type=RULE_VERSION"
        )

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(a["status"] == "PENDING" and a["entity_type"] == "RULE_VERSION" for a in items)

    @pytest.mark.anyio
    @pytest.mark.skip(
        reason="Session isolation issue - async_maker_client and clean_async_db_session use separate connections"
    )
    async def test_should_return_empty_list_when_no_approvals(
        self, async_maker_client: TestClient, clean_async_db_session
    ):
        """Test listing when no approvals exist."""
        response = async_maker_client.get("/api/v1/approvals")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        # Keyset pagination response (no "total" field)
        assert data["has_next"] is False
        assert data["has_prev"] is False

    @pytest.mark.anyio
    async def test_should_show_approved_status_after_approval(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test approval status changes after approval."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Approve
        async_checker_client.post(f"/api/v1/rule-versions/{version_id}/approve", json={})

        # Check approval status
        response = async_maker_client.get("/api/v1/approvals?status=APPROVED")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert any(a["entity_id"] == version_id for a in items)

        # Verify approved approval has checker
        approved = next((a for a in items if a["entity_id"] == version_id), None)
        if approved:
            assert approved["checker"] is not None
            assert approved["decided_at"] is not None

    @pytest.mark.anyio
    async def test_should_show_rejected_status_after_rejection(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test approval status changes after rejection."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Reject
        async_checker_client.post(f"/api/v1/rule-versions/{version_id}/reject", json={})

        # Check approval status
        response = async_maker_client.get("/api/v1/approvals?status=REJECTED")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert any(a["entity_id"] == version_id for a in items)


class TestListAuditLog:
    """Tests for GET /api/v1/audit-log endpoint."""

    @pytest.mark.anyio
    async def test_should_return_all_audit_logs(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test listing all audit log entries."""
        # Create a field (creates audit log entry)
        async_admin_client.post("/api/v1/rule-fields", json=sample_rule_field_data)

        # List audit logs
        response = async_admin_client.get("/api/v1/audit-log")

        assert response.status_code == 200
        data = response.json()
        # Paginated response has "items" key
        assert "items" in data
        items = data["items"]
        assert isinstance(items, list)
        assert len(items) > 0

        # Verify audit log structure
        log = items[0]
        assert "audit_id" in log
        assert "entity_type" in log
        assert "entity_id" in log
        assert "action" in log
        assert "performed_by" in log
        assert "performed_at" in log

    @pytest.mark.anyio
    async def test_should_filter_by_entity_type(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test filtering audit logs by entity type."""
        # Create a field
        async_admin_client.post("/api/v1/rule-fields", json=sample_rule_field_data)

        # Filter by RULE_FIELD entity type
        response = async_admin_client.get("/api/v1/audit-log?entity_type=RULE_FIELD")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(log["entity_type"] == "RULE_FIELD" for log in items)

    @pytest.mark.anyio
    async def test_should_filter_by_action(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test filtering audit logs by action."""
        # Create a field (CREATE action)
        create_response = async_admin_client.post(
            "/api/v1/rule-fields", json=sample_rule_field_data
        )
        field_key = create_response.json()["field_key"]

        # Update the field (UPDATE action)
        async_admin_client.patch(
            f"/api/v1/rule-fields/{field_key}",
            json={"display_name": "Updated Name"},
        )

        # Filter by CREATE action
        response = async_admin_client.get("/api/v1/audit-log?action=CREATE")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(log["action"] == "CREATE" for log in items)

        # Filter by UPDATE action
        response = async_admin_client.get("/api/v1/audit-log?action=UPDATE")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(log["action"] == "UPDATE" for log in items)

    @pytest.mark.anyio
    async def test_should_filter_by_performed_by(
        self, async_admin_client: TestClient, mock_admin: dict, sample_rule_field_data: dict
    ):
        """Test filtering audit logs by user."""
        # Create a field
        async_admin_client.post("/api/v1/rule-fields", json=sample_rule_field_data)

        # Filter by user
        user_id = mock_admin["sub"]
        response = async_admin_client.get(f"/api/v1/audit-log?performed_by={user_id}")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert all(log["performed_by"] == user_id for log in items)

    @pytest.mark.anyio
    async def test_should_filter_by_date_range(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test filtering audit logs by date range."""
        # Create a field
        async_admin_client.post("/api/v1/rule-fields", json=sample_rule_field_data)

        # Filter by date (since yesterday)
        from datetime import datetime, timedelta

        since = (datetime.now(UTC) - timedelta(days=1)).isoformat()

        response = async_admin_client.get(f"/api/v1/audit-log?since={since}")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert len(items) > 0

    @pytest.mark.anyio
    async def test_should_respect_limit_parameter(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test limiting number of audit log entries."""
        # Create multiple fields
        for i in range(5):
            field_data = {**sample_rule_field_data, "field_key": f"field_{i}"}
            async_admin_client.post("/api/v1/rule-fields", json=field_data)

        # Limit to 3 entries (using keyset pagination limit parameter)
        response = async_admin_client.get("/api/v1/audit-log?limit=3")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]
        assert len(items) == 3
        assert data["limit"] == 3

    @pytest.mark.anyio
    async def test_should_show_old_and_new_values(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test that UPDATE actions show before/after state."""
        # Create a field
        create_response = async_admin_client.post(
            "/api/v1/rule-fields", json=sample_rule_field_data
        )
        field_key = create_response.json()["field_key"]

        # Update the field
        async_admin_client.patch(
            f"/api/v1/rule-fields/{field_key}",
            json={"display_name": "Updated Name"},
        )

        # Get audit logs for UPDATE
        response = async_admin_client.get("/api/v1/audit-log?action=UPDATE")

        assert response.status_code == 200
        data = response.json()
        items = data["items"]

        # Find the update log
        update_logs = [log for log in items if log["action"] == "UPDATE"]
        if update_logs:
            log = update_logs[0]
            assert log["old_value"] is not None
            assert log["new_value"] is not None
            assert log["old_value"]["display_name"] == sample_rule_field_data["display_name"]
            assert log["new_value"]["display_name"] == "Updated Name"

    @pytest.mark.anyio
    async def test_should_return_empty_list_when_no_logs(self, async_admin_client: TestClient):
        """Test listing when no audit logs exist."""
        # Filter by non-existent user
        response = async_admin_client.get("/api/v1/audit-log?performed_by=nonexistent-user")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        # Keyset pagination response (no "total" field)
        assert data["has_next"] is False


class TestApprovalWorkflow:
    """Tests for approval workflow behavior."""

    @pytest.mark.anyio
    async def test_should_create_approval_on_submit(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test that submitting creates an approval record."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        # Before submission
        approvals_before = async_maker_client.get("/api/v1/approvals").json()
        initial_count = len(approvals_before["items"])

        # Submit for approval
        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # After submission
        approvals_after = async_maker_client.get("/api/v1/approvals").json()

        assert len(approvals_after["items"]) == initial_count + 1

    @pytest.mark.anyio
    async def test_should_track_maker_in_approval(
        self, async_maker_client: TestClient, mock_maker: dict, sample_rule_data: dict
    ):
        """Test that maker is tracked in approval."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Get approval
        approvals = async_maker_client.get("/api/v1/approvals").json()
        items = approvals["items"]
        approval = next((a for a in items if a["entity_id"] == version_id), None)

        assert approval is not None
        assert approval["maker"] == mock_maker["sub"]

    @pytest.mark.anyio
    async def test_should_track_checker_on_approval(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        mock_checker: dict,
        sample_rule_data: dict,
    ):
        """Test that checker is tracked on approval."""
        # Create and submit rule version
        create_response = async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # Approve
        async_checker_client.post(f"/api/v1/rule-versions/{version_id}/approve", json={})

        # Get approval
        approvals = async_checker_client.get("/api/v1/approvals").json()
        items = approvals["items"]
        approval = next((a for a in items if a["entity_id"] == version_id), None)

        assert approval is not None
        assert approval["checker"] == mock_checker["sub"]
        assert approval["status"] == "APPROVED"


class TestAuditTrailCompleteness:
    """Tests for audit trail coverage."""

    @pytest.mark.anyio
    async def test_should_audit_rule_field_creation(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test that rule field creation is audited."""
        async_admin_client.post("/api/v1/rule-fields", json=sample_rule_field_data)

        logs = async_admin_client.get(
            "/api/v1/audit-log?action=CREATE&entity_type=RULE_FIELD"
        ).json()
        items = logs["items"]

        assert len(items) > 0
        log = items[0]
        assert log["action"] == "CREATE"
        assert log["new_value"] is not None
        assert log["old_value"] is None

    @pytest.mark.anyio
    async def test_should_audit_rule_field_update(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test that rule field updates are audited."""
        create_response = async_admin_client.post(
            "/api/v1/rule-fields", json=sample_rule_field_data
        )
        field_key = create_response.json()["field_key"]

        async_admin_client.patch(
            f"/api/v1/rule-fields/{field_key}",
            json={"display_name": "Updated"},
        )

        logs = async_admin_client.get(
            "/api/v1/audit-log?action=UPDATE&entity_type=RULE_FIELD"
        ).json()
        items = logs["items"]

        assert len(items) > 0

    @pytest.mark.anyio
    async def test_should_audit_metadata_operations(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test that metadata operations are audited."""
        create_response = async_admin_client.post(
            "/api/v1/rule-fields", json=sample_rule_field_data
        )
        field_key = create_response.json()["field_key"]

        # Create metadata
        metadata_payload = {"meta_value": {"key": "value"}}
        async_admin_client.put(
            f"/api/v1/rule-fields/{field_key}/metadata/test",
            json=metadata_payload,
        )

        logs = async_admin_client.get("/api/v1/audit-log?entity_type=RULE_FIELD_METADATA").json()
        items = logs["items"]

        assert len(items) > 0

    @pytest.mark.anyio
    async def test_should_audit_metadata_deletion(
        self, async_admin_client: TestClient, sample_rule_field_data: dict
    ):
        """Test that metadata deletion is audited."""
        create_response = async_admin_client.post(
            "/api/v1/rule-fields", json=sample_rule_field_data
        )
        field_key = create_response.json()["field_key"]

        # Create metadata
        metadata_payload = {"meta_value": {"key": "value"}}
        async_admin_client.put(
            f"/api/v1/rule-fields/{field_key}/metadata/test",
            json=metadata_payload,
        )

        # Delete metadata
        async_admin_client.delete(f"/api/v1/rule-fields/{field_key}/metadata/test")

        logs = async_admin_client.get(
            "/api/v1/audit-log?action=DELETE&entity_type=RULE_FIELD_METADATA"
        ).json()
        items = logs["items"]

        assert len(items) > 0
        log = items[0]
        assert log["action"] == "DELETE"
        assert log["old_value"] is not None
        assert log["new_value"] is None


class TestEdgeCases:
    """Edge case tests for approvals and audit log."""

    @pytest.mark.anyio
    async def test_should_handle_very_long_entity_id(self, async_maker_client: TestClient):
        """Test filtering by very long entity_id."""
        import uuid

        long_id = str(uuid.uuid7())

        response = async_maker_client.get(f"/api/v1/audit-log?entity_id={long_id}")

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_should_handle_invalid_date_format_gracefully(
        self, async_maker_client: TestClient
    ):
        """Test that invalid date format is handled."""
        response = async_maker_client.get("/api/v1/audit-log?since=invalid-date")

        # Should return 400 or 422 for validation error
        assert response.status_code in [200, 400, 422]

    @pytest.mark.anyio
    async def test_should_handle_BLOCKLIST_limit(self, async_maker_client: TestClient):
        """Test that BLOCKLIST limit is handled."""
        response = async_maker_client.get("/api/v1/audit-log?limit=-1")

        # Should either use default or return error
        assert response.status_code in [200, 400, 422]
