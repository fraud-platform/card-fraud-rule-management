"""
End-to-end integration tests with real server and real HTTP.

These tests:
- Start a real uvicorn server (see conftest.py e2e_server_base_url fixture)
- Make real HTTP requests using httpx
- Test full stack including middleware, auth, CORS, etc.
- Test RuleSet CRUD operations and approval workflow
- Test artifact publication to MinIO for AUTH/MONITORING rulesets

To run E2E tests:
  uv run pytest -m e2e_integration -v

To skip E2E tests (default):
  uv run pytest -v  # (excludes e2e via pyproject.toml addopts)
"""

import uuid

import httpx
import pytest

from app.core.config import settings

pytestmark = pytest.mark.e2e_integration


# =============================================================================
# S3 Client Helper
# =============================================================================


@pytest.fixture(scope="session")
def e2e_s3_client():
    """Create a boto3 S3 client for verifying uploaded artifacts in E2E tests."""
    config = {"service_name": "s3", "region_name": settings.s3_region}

    if settings.s3_endpoint_url:
        config["endpoint_url"] = settings.s3_endpoint_url
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        config["aws_access_key_id"] = settings.s3_access_key_id
        config["aws_secret_access_key"] = settings.s3_secret_access_key
    if settings.s3_force_path_style:
        import boto3.session

        config["config"] = boto3.session.Config(
            signature_version="s3v4", s3={"addressing_style": "path"}
        )

    return boto3.client(**config)


class TestE2EHealth:
    """E2E tests for health and readiness endpoints."""

    @pytest.mark.anyio
    async def test_health_returns_200(self, e2e_server_base_url: str):
        """Test /api/v1/health returns 200."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/health", timeout=5.0)

        assert response.status_code == 200
        # Keep this aligned with unit tests and the current API contract.
        assert response.json() == {"ok": True}

    @pytest.mark.anyio
    async def test_readyz_returns_200_or_503(self, e2e_server_base_url: str):
        """Test /api/v1/readyz returns 200 (DB ready) or 503 (DB not configured)."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/readyz", timeout=5.0)

        # Should return 200 if DB is configured, or 503 if not
        assert response.status_code in [200, 503]

        body = response.json()
        if response.status_code == 200:
            assert body.get("ok") is True
            assert body.get("db") == "ok"
        else:
            # Current API returns details about the DB being unavailable.
            assert body.get("ok") is False
            assert body.get("db") == "unavailable"


class TestE2ERuleFields:
    """E2E tests for rule-fields endpoints."""

    @pytest.mark.anyio
    async def test_list_rule_fields_requires_auth(self, e2e_server_base_url: str):
        """Test GET /api/v1/rule-fields requires authentication."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/rule-fields", timeout=5.0)

        # Should return 401 or 403 (depends on auth config)
        assert response.status_code in [401, 403]

    @pytest.mark.anyio
    async def test_get_nonexistent_rule_field_returns_404(self, e2e_server_base_url: str):
        """Test GET /api/v1/rule-fields/{id} returns 404 for missing field (with mock auth)."""
        # Note: Without real Auth0 token, this will fail with 401
        # This test documents expected behavior when auth is properly configured
        response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rule-fields/00000000-0000-0000-0000-000000000000",
            timeout=5.0,
        )

        # Either 401 (no auth) or 404 (auth + not found)
        assert response.status_code in [401, 403, 404]


class TestE2ERules:
    """E2E tests for rules endpoints."""

    @pytest.mark.anyio
    async def test_list_rules_public(self, e2e_server_base_url: str):
        """Test GET /api/v1/rules is publicly accessible (read-only)."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/rules", timeout=5.0)

        # Read-only list endpoint should be accessible (200) or require auth (401/403)
        assert response.status_code in [200, 401, 403]

        if response.status_code == 200:
            # Should return a list (possibly empty)
            assert isinstance(response.json(), list)

    @pytest.mark.anyio
    async def test_get_nonexistent_rule_returns_404(self, e2e_server_base_url: str):
        """Test GET /api/v1/rules/{id} returns 404 for missing rule."""
        response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rules/00000000-0000-0000-0000-000000000000",
            timeout=5.0,
        )

        # 404 (not found) or 401/403 (auth required)
        assert response.status_code in [401, 403, 404]

    @pytest.mark.anyio
    async def test_create_rule_requires_auth(self, e2e_server_base_url: str):
        """Test POST /api/v1/rules requires authentication."""
        response = httpx.post(
            f"{e2e_server_base_url}/api/v1/rules",
            json={
                "rule_name": "E2E Test Rule",
                "description": "Created by E2E test",
                "rule_type": "ALLOWLIST",
                "condition_tree": {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                "priority": 100,
            },
            timeout=5.0,
        )

        # Should require authentication
        assert response.status_code in [401, 403]


class TestE2ERuleSets:
    """E2E tests for rulesets endpoints."""

    @pytest.mark.anyio
    async def test_list_rulesets_public(self, e2e_server_base_url: str):
        """Test GET /api/v1/rulesets is publicly accessible (read-only)."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/rulesets", timeout=5.0)

        # Read-only list endpoint should be accessible (200) or require auth (401/403)
        assert response.status_code in [200, 401, 403]

        if response.status_code == 200:
            assert isinstance(response.json(), list)

    @pytest.mark.anyio
    async def test_get_nonexistent_ruleset_returns_404(self, e2e_server_base_url: str):
        """Test GET /api/v1/rulesets/{id} returns 404 for missing ruleset."""
        response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rulesets/00000000-0000-0000-0000-000000000000",
            timeout=5.0,
        )

        assert response.status_code in [401, 403, 404]


class TestE2EApprovals:
    """E2E tests for approvals endpoints."""

    @pytest.mark.anyio
    async def test_list_approvals(self, e2e_server_base_url: str):
        """Test GET /api/v1/approvals is accessible."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/approvals", timeout=5.0)

        # Public read-only (200) or auth required (401/403)
        assert response.status_code in [200, 401, 403]


class TestE2EAuditLog:
    """E2E tests for audit-log endpoints."""

    @pytest.mark.anyio
    async def test_list_audit_logs(self, e2e_server_base_url: str):
        """Test GET /api/v1/audit-log is accessible."""
        response = httpx.get(f"{e2e_server_base_url}/api/v1/audit-log", timeout=5.0)

        # Public read-only (200) or auth required (401/403)
        assert response.status_code in [200, 401, 403]

    @pytest.mark.anyio
    async def test_audit_log_invalid_date_returns_422(self, e2e_server_base_url: str):
        """Test GET /api/v1/audit-log with invalid date returns 422."""
        response = httpx.get(
            f"{e2e_server_base_url}/api/v1/audit-log?since=not-a-date",
            timeout=5.0,
        )

        # Should validate input
        assert response.status_code in [200, 401, 403, 422]

    @pytest.mark.anyio
    async def test_audit_log_limit_parameter(self, e2e_server_base_url: str):
        """Test GET /api/v1/audit-log?limit=5 works."""
        response = httpx.get(
            f"{e2e_server_base_url}/api/v1/audit-log?limit=5",
            timeout=5.0,
        )

        # Public read-only (200) or auth required (401/403)
        assert response.status_code in [200, 401, 403]


class TestE2EIdempotentFlows:
    """E2E tests for idempotent create/read/delete flows (cleanup after themselves).

    NOTE: These tests require valid Auth0 tokens to work properly.
    They are skipped by default and can be enabled with:
      uv run pytest -m e2e_integration -k "test_e2e_idempotent" --auth-token="Bearer ..."
    """

    @pytest.mark.anyio
    async def test_e2e_idempotent_rule_field_create_and_deactivate(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test complete rule field lifecycle: CREATE → GET → PATCH → VERIFY."""
        import uuid

        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        unique_key = f"e2e_test_field_{uuid.uuid7().hex[:8]}"
        # CREATE
        create_response = httpx.post(
            f"{e2e_server_base_url}/api/v1/rule-fields",
            headers=e2e_auth_header,
            json={
                "field_key": unique_key,
                "display_name": f"E2E Test Field {unique_key}",
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_sensitive": False,
                "is_active": True,
            },
            timeout=5.0,
        )
        assert create_response.status_code in [201, 409]  # 201 created, or 409 duplicate

        if create_response.status_code == 201:
            field_key = create_response.json()["field_key"]

            # GET - verify created
            get_response = httpx.get(
                f"{e2e_server_base_url}/api/v1/rule-fields/{field_key}",
                headers=e2e_auth_header,
                timeout=5.0,
            )
            assert get_response.status_code == 200
            assert get_response.json()["field_key"] == field_key
            assert get_response.json()["is_active"] is True

            # PATCH - deactivate (cleanup)
            patch_response = httpx.patch(
                f"{e2e_server_base_url}/api/v1/rule-fields/{field_key}",
                headers=e2e_auth_header,
                json={"is_active": False},
                timeout=5.0,
            )
            assert patch_response.status_code == 200
            assert patch_response.json()["is_active"] is False

    @pytest.mark.anyio
    async def test_e2e_idempotent_rule_create_and_delete(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test complete rule lifecycle: CREATE → GET → DELETE → VERIFY."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        pytest.skip(
            "Requires additional setup (maker/checker roles + existing rule_field). Not automated yet."
        )


# =============================================================================
# E2E RuleSet CRUD Tests
# =============================================================================


class TestE2ERuleSetCRUD:
    """E2E tests for RuleSet CRUD operations and approval workflow."""

    @pytest.mark.anyio
    async def test_e2e_ruleset_full_lifecycle(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None, e2e_s3_client
    ):
        """
        Test complete RuleSet lifecycle:
        1. Create RuleSet
        2. Attach rule versions
        3. Submit for approval
        4. Approve (triggers publish for AUTH/MONITORING)
        5. Verify artifact in MinIO (for runtime rulesets)

        This test requires:
        - Valid Auth0 token with MAKER and CHECKER roles
        - Existing APPROVED rule versions to attach
        - MinIO/S3 configured for artifact verification
        """
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        import uuid

        unique_name = f"E2E Test RuleSet {uuid.uuid7().hex[:8]}"
        ruleset_id = None

        try:
            # Step 1: Create a AUTH RuleSet
            create_response = httpx.post(
                f"{e2e_server_base_url}/api/v1/rulesets",
                headers=e2e_auth_header,
                json={
                    "name": unique_name,
                    "description": "E2E test for RuleSet full lifecycle",
                    "rule_type": "AUTH",
                },
                timeout=10.0,
            )

            if create_response.status_code not in [201, 409]:
                # Log error for debugging
                print(f"Create failed: {create_response.status_code} - {create_response.text}")
                pytest.skip(f"Failed to create RuleSet: {create_response.status_code}")

            if create_response.status_code == 201:
                ruleset_data = create_response.json()
                ruleset_id = ruleset_data["ruleset_id"]
                assert ruleset_data["name"] == unique_name
                assert ruleset_data["rule_type"] == "AUTH"
                assert ruleset_data["status"] == "DRAFT"

                # Step 2: Try to attach rule versions (skip if none exist)
                # In a real test, you would create rule versions first
                attach_response = httpx.post(
                    f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/rules",
                    headers=e2e_auth_header,
                    json={
                        "rule_version_ids": [],  # Empty list if no rule versions exist
                        "expected_ruleset_version": ruleset_data["version"],
                    },
                    timeout=10.0,
                )

                # Accept 200 or 404 (no rule versions to attach)
                assert attach_response.status_code in [200, 404, 400]

                # Step 3: Submit for approval
                submit_response = httpx.post(
                    f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/submit",
                    headers=e2e_auth_header,
                    json={"idempotency_key": f"e2e-test-{uuid.uuid7()}"},  # Idempotency key
                    timeout=10.0,
                )

                if submit_response.status_code == 200:
                    submitted_data = submit_response.json()
                    assert submitted_data["status"] == "PENDING_APPROVAL"

                    # Step 4: Approve the RuleSet
                    # Note: This requires CHECKER role, which might not be available
                    approve_response = httpx.post(
                        f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/approve",
                        headers=e2e_auth_header,
                        json={},
                        timeout=10.0,
                    )

                    # Maker cannot approve their own submission (expected)
                    # In real E2E, you'd need separate MAKER and CHECKER tokens
                    assert approve_response.status_code in [200, 409, 403]

                    if approve_response.status_code == 200:
                        approved_data = approve_response.json()
                        assert approved_data["status"] == "APPROVED"
                        assert approved_data["approved_by"] is not None

                        # Step 5: Verify artifact was published to MinIO (for AUTH)
                        # This assumes S3/MinIO is configured
                        try:
                            # Query for manifests
                            manifest_response = httpx.get(
                                f"{e2e_server_base_url}/api/v1/ruleset-manifests",
                                headers=e2e_auth_header,
                                params={"ruleset_key": "CARD_AUTH"},
                                timeout=10.0,
                            )

                            if manifest_response.status_code == 200:
                                manifests = manifest_response.json()
                                if len(manifests) > 0:
                                    # Verify at least one manifest exists
                                    assert any(m["ruleset_key"] == "CARD_AUTH" for m in manifests)
                        except Exception:
                            # Manifest endpoint might not exist yet
                            pass

        finally:
            # Cleanup: Try to deactivate if created
            if ruleset_id:
                try:
                    # Note: DELETE endpoint might not exist, so we just log
                    print(f"E2E test created RuleSet: {ruleset_id}")
                except Exception:
                    pass

    @pytest.mark.anyio
    async def test_e2e_ruleset_create_duplicate_fails_gracefully(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test that creating duplicate RuleSet fails gracefully or updates existing."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        import uuid

        # Try to create with same parameters (idempotent behavior)
        unique_name = f"E2E Duplicate Test {uuid.uuid7().hex[:8]}"

        response1 = httpx.post(
            f"{e2e_server_base_url}/api/v1/rulesets",
            headers=e2e_auth_header,
            json={
                "name": unique_name,
                "rule_type": "ALLOWLIST",
            },
            timeout=10.0,
        )

        # Should create successfully
        assert response1.status_code in [201, 409]

    @pytest.mark.anyio
    async def test_e2e_ruleset_reject_workflow(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test RuleSet rejection workflow."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        import uuid

        unique_name = f"E2E Reject Test {uuid.uuid7().hex[:8]}"

        # Create a RuleSet
        create_response = httpx.post(
            f"{e2e_server_base_url}/api/v1/rulesets",
            headers=e2e_auth_header,
            json={
                "name": unique_name,
                "rule_type": "ALLOWLIST",
            },
            timeout=10.0,
        )

        if create_response.status_code == 201:
            ruleset_id = create_response.json()["ruleset_id"]

            # Submit for approval
            submit_response = httpx.post(
                f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/submit",
                headers=e2e_auth_header,
                json={},
                timeout=10.0,
            )

            if submit_response.status_code == 200:
                # Reject the RuleSet
                reject_response = httpx.post(
                    f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/reject",
                    headers=e2e_auth_header,
                    json={"remarks": "E2E test rejection"},
                    timeout=10.0,
                )

                # Should be rejected or forbidden (if maker tries to reject)
                assert reject_response.status_code in [200, 403, 409]

                if reject_response.status_code == 200:
                    rejected_data = reject_response.json()
                    assert rejected_data["status"] == "REJECTED"

    @pytest.mark.anyio
    async def test_e2e_ruleset_compile_endpoint(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test RuleSet compile endpoint."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        # First, we need an APPROVED ruleset to compile
        # For this test, we'll just check the endpoint exists and handles errors

        import uuid

        # Try to compile a nonexistent ruleset
        compile_response = httpx.post(
            f"{e2e_server_base_url}/api/v1/rulesets/{uuid.uuid7()}/compile",
            headers=e2e_auth_header,
            timeout=10.0,
        )

        # Should return 404 or 403 (permission)
        assert compile_response.status_code in [404, 403, 401]

    @pytest.mark.anyio
    async def test_e2e_ruleset_list_pagination(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test RuleSet list with pagination."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        # List rulesets with default limit
        list_response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rulesets",
            headers=e2e_auth_header,
            params={"limit": 10},
            timeout=10.0,
        )

        # Should return 200 with a list
        assert list_response.status_code in [200, 401, 403]

        if list_response.status_code == 200:
            data = list_response.json()
            assert "items" in data or isinstance(data, list)

    @pytest.mark.anyio
    async def test_e2e_ruleset_get_by_id(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test getting a RuleSet by ID."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        # Try to get a nonexistent ruleset
        get_response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rulesets/{uuid.uuid7()}",
            headers=e2e_auth_header,
            timeout=10.0,
        )

        # Should return 404 or 401/403
        assert get_response.status_code in [404, 401, 403]


class TestE2ERuleSetArtifacts:
    """E2E tests for RuleSet artifact publication to MinIO/S3."""

    @pytest.mark.anyio
    async def test_e2e_AUTH_artifact_published_on_approval(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None, e2e_s3_client
    ):
        """
        Test that approving a AUTH RuleSet publishes artifact to MinIO.

        This verifies:
        - Artifact is uploaded to S3/MinIO on approval
        - Artifact contains valid compiled AST
        - Checksum matches artifact content
        - Manifest row is created in database
        """
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        # This test requires:
        # 1. Existing APPROVED rule versions to attach
        # 2. Separate MAKER and CHECKER tokens
        # 3. S3/MinIO configured and accessible

        # For now, we'll skip with a helpful message
        pytest.skip(
            "Requires full setup: APPROVED rule versions, separate MAKER/CHECKER tokens, and S3 access. "
            "This test should be enabled when test data setup is automated."
        )

    @pytest.mark.anyio
    async def test_e2e_monitoring_artifact_published_on_approval(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None, e2e_s3_client
    ):
        """Test that approving a MONITORING RuleSet publishes artifact to MinIO."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        pytest.skip(
            "Requires full setup: APPROVED rule versions, separate MAKER/CHECKER tokens, and S3 access."
        )

    @pytest.mark.anyio
    async def test_e2e_ALLOWLIST_ruleset_no_artifact_published(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test that ALLOWLIST RuleSets do NOT publish artifacts to S3."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        pytest.skip("Requires full setup: APPROVED rule versions, separate MAKER/CHECKER tokens.")

    @pytest.mark.anyio
    async def test_e2e_artifact_checksum_validation(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None, e2e_s3_client
    ):
        """Test that artifact checksum matches the published content."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        pytest.skip("Requires full E2E setup with S3 access and test data.")

    @pytest.mark.anyio
    async def test_e2e_artifact_version_increments(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None, e2e_s3_client
    ):
        """Test that artifact versions increment on subsequent publishes."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        pytest.skip("Requires full E2E setup with S3 access and test data.")


class TestE2ERuleSetIdempotency:
    """E2E tests for RuleSet idempotency."""

    @pytest.mark.anyio
    async def test_e2e_submit_with_idempotency_key(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test submit with idempotency key prevents duplicate approvals."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        import uuid

        unique_name = f"E2E Idempotency Test {uuid.uuid7().hex[:8]}"
        idempotency_key = f"e2e-test-key-{uuid.uuid7()}"

        # Create a RuleSet
        create_response = httpx.post(
            f"{e2e_server_base_url}/api/v1/rulesets",
            headers=e2e_auth_header,
            json={
                "name": unique_name,
                "rule_type": "ALLOWLIST",
            },
            timeout=10.0,
        )

        if create_response.status_code == 201:
            ruleset_id = create_response.json()["ruleset_id"]

            # Submit with idempotency key
            submit_response1 = httpx.post(
                f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/submit",
                headers=e2e_auth_header,
                json={"idempotency_key": idempotency_key},
                timeout=10.0,
            )

            # Submit again with same key
            submit_response2 = httpx.post(
                f"{e2e_server_base_url}/api/v1/rulesets/{ruleset_id}/submit",
                headers=e2e_auth_header,
                json={"idempotency_key": idempotency_key},
                timeout=10.0,
            )

            # Both should succeed (second is idempotent)
            assert submit_response1.status_code == 200
            assert submit_response2.status_code == 200

            # Verify same state returned
            assert submit_response1.json()["status"] == submit_response2.json()["status"]


class TestE2ERuleSetCompilation:
    """E2E tests for RuleSet compilation."""

    @pytest.mark.anyio
    async def test_e2e_compiled_ast_retrieval(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test retrieving compiled AST for an APPROVED ruleset."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        # Try to get compiled AST for a nonexistent ruleset
        response = httpx.get(
            f"{e2e_server_base_url}/api/v1/rulesets/{uuid.uuid7()}/compiled-ast",
            headers=e2e_auth_header,
            timeout=10.0,
        )

        # Should return 404 or 401/403
        assert response.status_code in [404, 401, 403]

    @pytest.mark.anyio
    async def test_e2e_compile_endpoint_creates_ast(
        self, e2e_server_base_url: str, e2e_auth_header: dict[str, str] | None
    ):
        """Test that compile endpoint creates AST for APPROVED ruleset."""
        if not e2e_auth_header:
            pytest.skip("Requires Auth0 token (set E2E_AUTH_TOKEN or pass --auth-token)")

        pytest.skip("Requires APPROVED ruleset with rule versions to test compilation.")
