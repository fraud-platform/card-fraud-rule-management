"""
Comprehensive integration tests for Rules API endpoints.

Tests cover:
- POST /rules (create rule with initial version)
- GET /rules (list rules with filters)
- GET /rules/{rule_id} (get single rule)
- POST /rules/{rule_id}/versions (create new version)
- POST /rule-versions/{rule_version_id}/submit (submit for approval)
- POST /rule-versions/{rule_version_id}/approve (approve by checker)
- POST /rule-versions/{rule_version_id}/reject (reject by checker)
- Condition tree validation
- Maker-checker workflow enforcement
- Authentication and authorization
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app


class TestCreateRule:
    """Tests for POST /api/v1/rules endpoint."""

    @pytest.mark.anyio
    async def test_should_create_rule_with_initial_version(
        self,
        async_maker_client: TestClient,
        async_db_session: AsyncSession,
        sample_rule_data: dict,
    ):
        """Test creating a new rule with initial version."""
        response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)

        assert response.status_code == 201
        data = response.json()
        assert data["rule_name"] == sample_rule_data["rule_name"]
        assert data["rule_type"] == sample_rule_data["rule_type"]
        assert data["current_version"] == 1
        assert data["status"] == "DRAFT"
        assert "rule_id" in data
        assert "created_by" in data

    @pytest.mark.anyio
    async def test_should_create_rule_without_description(self, async_maker_client: TestClient):
        """Test creating rule with optional description omitted."""
        payload = {
            "rule_name": "Minimal Rule",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 500,
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["description"] is None

    @pytest.mark.anyio
    async def test_should_validate_rule_type(self, async_maker_client: TestClient):
        """Test that invalid rule_type is rejected."""
        payload = {
            "rule_name": "Invalid Rule",
            "rule_type": "INVALID_TYPE",  # Not a valid RuleType
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 100,
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)

        # Should fail validation
        assert response.status_code in [400, 422]

    @pytest.mark.anyio
    @pytest.mark.skip(
        reason="Session isolation issue - async_maker_client uses separate connection"
    )
    async def test_should_return_empty_list_when_no_rules(self, async_maker_client: TestClient):
        """Test listing when no rules exist."""
        response = await async_maker_client.get("/api/v1/rules")

        assert response.status_code == 200
        data = response.json()
        # Paginated response has "items" key
        items = data["items"]
        # When no rules exist, should return empty list
        assert len(items) == 0

    @pytest.mark.anyio
    async def test_should_create_new_version(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test creating a new version of an existing rule."""
        # Create initial rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create new version
        new_version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 2000,  # Different threshold
            },
            "priority": 150,
        }

        response = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=new_version_payload
        )

        assert response.status_code == 201
        data = response.json()
        assert data["rule_id"] == rule_id
        assert data["version"] == 2  # Second version
        assert data["status"] == "DRAFT"
        assert data["priority"] == 150
        assert "rule_version_id" in data

    @pytest.mark.anyio
    async def test_should_increment_version_number(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test that version numbers increment correctly."""
        # Create initial rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create multiple versions
        version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 100,
        }

        response1 = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        response2 = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )

        assert response1.json()["version"] == 2
        assert response2.json()["version"] == 3

    @pytest.mark.anyio
    async def test_should_return_404_when_rule_not_found(self, async_maker_client: TestClient):
        """Test creating version for non-existent rule."""
        non_existent_id = str(uuid.uuid7())
        payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 100,
        }

        response = await async_maker_client.post(
            f"/api/v1/rules/{non_existent_id}/versions", json=payload
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_should_require_maker_role(
        self, async_authenticated_client: TestClient, sample_rule_data: dict
    ):
        """Test that MAKER role is required."""
        # This is simplified - in real test would use proper fixtures
        payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 100,
        }

        # Non-MAKER user tries to create version
        response = await async_authenticated_client.post(
            f"/api/v1/rules/{uuid.uuid7()}/versions", json=payload
        )

        assert response.status_code == 403


class TestSubmitRuleVersion:
    """Tests for POST /api/v1/rule-versions/{rule_version_id}/submit endpoint."""

    @pytest.mark.anyio
    async def test_should_submit_version_for_approval(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test submitting a rule version for approval."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_data = create_response.json()

        # Get the initial version ID (need to query versions endpoint or use known pattern)
        # For this test, we'll create a new version to get the ID
        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_data['rule_id']}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        # Submit for approval
        response = await async_maker_client.post(
            f"/api/v1/rule-versions/{version_id}/submit", json={}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PENDING_APPROVAL"
        assert data["rule_version_id"] == version_id

    @pytest.mark.anyio
    async def test_should_require_maker_role(self, async_authenticated_client: TestClient):
        """Test that MAKER role is required to submit."""
        version_id = str(uuid.uuid7())

        response = await async_authenticated_client.post(
            f"/api/v1/rule-versions/{version_id}/submit", json={}
        )

        assert response.status_code == 403


class TestApproveRuleVersion:
    """Tests for POST /api/v1/rule-versions/{rule_version_id}/approve endpoint."""

    @pytest.mark.anyio
    async def test_should_approve_when_different_user(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test that checker can approve version created by maker."""
        # MAKER creates and submits rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_data = create_response.json()

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_data['rule_id']}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        # Submit for approval
        await async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # CHECKER approves (different user)
        response = await async_checker_client.post(
            f"/api/v1/rule-versions/{version_id}/approve", json={}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "APPROVED"

    @pytest.mark.anyio
    async def test_should_reject_when_maker_equals_checker(
        self, async_db_session: AsyncSession, mock_maker_checker: dict, sample_rule_data: dict
    ):
        """Test that maker cannot approve their own submission (maker-checker violation)."""
        import httpx

        from app.core.dependencies import get_async_db_session, get_current_user

        app = create_app()

        def override_get_async_db():
            yield async_db_session

        async def override_user():
            return mock_maker_checker

        app.dependency_overrides[get_async_db_session] = override_get_async_db
        app.dependency_overrides[get_current_user] = override_user

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create and submit as maker
            create_response = await client.post("/api/v1/rules", json=sample_rule_data)
            rule_data = create_response.json()

            version_payload = {
                "condition_tree": sample_rule_data["condition_tree"],
                "priority": 100,
            }
            version_response = await client.post(
                f"/api/v1/rules/{rule_data['rule_id']}/versions", json=version_payload
            )
            version_id = version_response.json()["rule_version_id"]

            await client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

            # Try to approve as same user
            response = await client.post(f"/api/v1/rule-versions/{version_id}/approve", json={})

            assert response.status_code in [
                400,
                409,
            ]  # Accept either validation or conflict semantics
            data = response.json()
            assert data["error"] == "MakerCheckerViolation"

    @pytest.mark.anyio
    async def test_should_return_404_when_no_pending_approval(
        self, async_checker_client: TestClient
    ):
        """Test approving version with no pending approval."""
        version_id = str(uuid.uuid7())

        response = await async_checker_client.post(
            f"/api/v1/rule-versions/{version_id}/approve", json={}
        )

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"

    @pytest.mark.anyio
    async def test_should_require_checker_role(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test that CHECKER role is required to approve."""
        # Create and submit version
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_data = create_response.json()

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_data['rule_id']}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        await async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # MAKER (not CHECKER) tries to approve
        response = await async_maker_client.post(
            f"/api/v1/rule-versions/{version_id}/approve", json={}
        )

        assert response.status_code == 403


class TestRejectRuleVersion:
    """Tests for POST /api/v1/rule-versions/{rule_version_id}/reject endpoint."""

    @pytest.mark.anyio
    async def test_should_reject_when_different_user(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test that checker can reject version created by maker."""
        # MAKER creates and submits rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_data = create_response.json()

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_data['rule_id']}/versions", json=version_payload
        )
        version_id = version_response.json()["rule_version_id"]

        # Submit for approval
        await async_maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

        # CHECKER rejects (different user)
        response = await async_checker_client.post(
            f"/api/v1/rule-versions/{version_id}/reject", json={}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "REJECTED"

    @pytest.mark.anyio
    async def test_should_reject_when_maker_equals_checker(
        self, async_db_session: AsyncSession, mock_maker_checker: dict, sample_rule_data: dict
    ):
        """Test that maker cannot reject their own submission."""
        import httpx

        from app.core.dependencies import get_async_db_session, get_current_user

        app = create_app()

        def override_get_async_db():
            yield async_db_session

        async def override_user():
            return mock_maker_checker

        app.dependency_overrides[get_async_db_session] = override_get_async_db
        app.dependency_overrides[get_current_user] = override_user

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create and submit as maker
            create_response = await client.post("/api/v1/rules", json=sample_rule_data)
            rule_data = create_response.json()

            version_payload = {
                "condition_tree": sample_rule_data["condition_tree"],
                "priority": 100,
            }
            version_response = await client.post(
                f"/api/v1/rules/{rule_data['rule_id']}/versions", json=version_payload
            )
            version_id = version_response.json()["rule_version_id"]

            await client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

            # Try to reject as same user
            response = await client.post(f"/api/v1/rule-versions/{version_id}/reject", json={})

            assert response.status_code in [400, 409]
            data = response.json()
            assert data["error"] == "MakerCheckerViolation"

    @pytest.mark.anyio
    async def test_should_require_checker_role(self, async_maker_client: TestClient):
        """Test that CHECKER role is required to reject."""
        version_id = str(uuid.uuid7())

        response = await async_maker_client.post(
            f"/api/v1/rule-versions/{version_id}/reject", json={}
        )

        assert response.status_code == 403


class TestRuleConditionTreeValidation:
    """Tests for condition tree validation."""

    @pytest.mark.anyio
    async def test_should_accept_simple_condition(self, async_maker_client: TestClient):
        """Test simple condition tree."""
        payload = {
            "rule_name": "Simple Condition",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_should_accept_and_condition(self, async_maker_client: TestClient):
        """Test AND logical operator."""
        payload = {
            "rule_name": "AND Condition",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "AND",
                "conditions": [
                    {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 1000},
                    {"type": "CONDITION", "field": "mcc", "operator": "EQ", "value": "5411"},
                ],
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_should_accept_or_condition(self, async_maker_client: TestClient):
        """Test OR logical operator."""
        payload = {
            "rule_name": "OR Condition",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "OR",
                "conditions": [
                    {"type": "CONDITION", "field": "country", "operator": "EQ", "value": "US"},
                    {"type": "CONDITION", "field": "country", "operator": "EQ", "value": "CA"},
                ],
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)
        assert response.status_code == 201

    @pytest.mark.anyio
    async def test_should_accept_nested_conditions(self, async_maker_client: TestClient):
        """Test nested logical operators."""
        payload = {
            "rule_name": "Nested Condition",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "AND",
                "conditions": [
                    {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 1000},
                    {
                        "type": "OR",
                        "conditions": [
                            {
                                "type": "CONDITION",
                                "field": "country",
                                "operator": "EQ",
                                "value": "US",
                            },
                            {
                                "type": "CONDITION",
                                "field": "country",
                                "operator": "EQ",
                                "value": "CA",
                            },
                        ],
                    },
                ],
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)
        assert response.status_code == 201


class TestRuleEdgeCases:
    """Edge case tests for rules."""

    @pytest.mark.anyio
    async def test_should_handle_very_high_priority(self, async_maker_client: TestClient):
        """Test rule with very high priority value."""
        payload = {
            "rule_name": "High Priority",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 99999,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)
        # Priority is constrained (DB/validation); very large values should be rejected.
        assert response.status_code in (409, 422)

    @pytest.mark.anyio
    async def test_should_handle_unicode_in_rule_name(self, async_maker_client: TestClient):
        """Test rule name with Unicode characters."""
        payload = {
            "rule_name": "规则测试 - Rule Test",
            "rule_type": "ALLOWLIST",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "priority": 100,
        }

        response = await async_maker_client.post("/api/v1/rules", json=payload)
        assert response.status_code == 201
        assert response.json()["rule_name"] == "规则测试 - Rule Test"


class TestSubmitRuleVersionIdempotency:
    """Tests for idempotency key support on rule version submit."""

    @pytest.mark.anyio
    async def test_should_prevent_duplicate_submissions_with_idempotency_key(
        self, async_maker_client: TestClient, sample_rule_data: dict, async_db_session: AsyncSession
    ):
        """Test that duplicate submissions with same idempotency key return existing approval."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create new version
        version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 2000,
            },
            "priority": 150,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Submit with idempotency key
        idempotency_key = "test-idempotency-abc123"
        submit_payload = {
            "idempotency_key": idempotency_key,
            "remarks": "First submission",
        }
        response1 = await async_maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit", json=submit_payload
        )

        assert response1.status_code == 200
        assert response1.json()["status"] == "PENDING_APPROVAL"

        # Try to submit again with same idempotency key
        submit_payload2 = {
            "idempotency_key": idempotency_key,
            "remarks": "Second submission attempt",
        }
        response2 = await async_maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit", json=submit_payload2
        )

        # Should succeed without creating duplicate approval
        assert response2.status_code == 200
        assert response2.json()["status"] == "PENDING_APPROVAL"

        # Verify only one approval record exists
        from sqlalchemy import select

        from app.db.models import Approval

        stmt = select(Approval).where(Approval.entity_id == rule_version_id)
        result = await async_db_session.execute(stmt)
        approvals = result.scalars().all()
        assert len(approvals) == 1
        assert approvals[0].idempotency_key == idempotency_key

    @pytest.mark.anyio
    async def test_should_allow_different_idempotency_keys(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test that different idempotency keys create different approvals."""
        # Create rule and version
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create another version after rejecting the first one
        version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 3000,
            },
            "priority": 200,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Submit with first idempotency key
        submit_payload1 = {
            "idempotency_key": "key-001",
            "remarks": "First submission",
        }
        response1 = await async_maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit", json=submit_payload1
        )
        assert response1.status_code == 200

        # Reject the first submission via API (checker_client has CHECKER role)
        reject_response = await async_checker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/reject", json={}
        )
        assert reject_response.status_code == 200

        # Submit again with different idempotency key
        submit_payload2 = {
            "idempotency_key": "key-002",
            "remarks": "Second submission",
        }
        response2 = await async_maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit", json=submit_payload2
        )

        # Should create new approval since status is no longer PENDING
        assert response2.status_code == 200

    @pytest.mark.anyio
    async def test_should_work_without_idempotency_key(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test that submissions work without idempotency key (backwards compatibility)."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create new version
        version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 2000,
            },
            "priority": 150,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Submit without idempotency key
        submit_payload = {}
        response = await async_maker_client.post(
            f"/api/v1/rule-versions/{rule_version_id}/submit", json=submit_payload
        )

        # Should succeed
        assert response.status_code == 200
        assert response.json()["status"] == "PENDING_APPROVAL"


class TestGetRuleVersion:
    """Tests for GET /api/v1/rule-versions/{rule_version_id} endpoint."""

    @pytest.mark.anyio
    async def test_should_return_rule_version_details(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test retrieving a specific rule version by ID (for analyst deep links)."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create a new version
        version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 2000,
            },
            "priority": 150,
            "scope": {"network": ["VISA"], "mcc": ["7995"]},
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Get rule version by ID
        response = await async_maker_client.get(f"/api/v1/rule-versions/{rule_version_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["rule_version_id"] == rule_version_id
        assert data["rule_id"] == rule_id
        assert data["version"] == 2
        assert data["rule_name"] == sample_rule_data["rule_name"]
        assert data["rule_type"] == sample_rule_data["rule_type"]
        assert data["priority"] == 150
        assert data["status"] == "DRAFT"
        assert "condition_tree" in data
        assert "scope" in data
        assert data["scope"]["network"] == ["VISA"]

    @pytest.mark.anyio
    async def test_should_return_404_for_nonexistent_version(self, async_maker_client: TestClient):
        """Test retrieving non-existent rule version."""
        non_existent_id = str(uuid.uuid7())

        response = await async_maker_client.get(f"/api/v1/rule-versions/{non_existent_id}")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"

    @pytest.mark.anyio
    async def test_should_include_approved_fields_when_approved(
        self,
        async_maker_client: TestClient,
        async_checker_client: TestClient,
        sample_rule_data: dict,
    ):
        """Test that approved_at and approved_by are populated after approval."""
        # Create and submit rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        version_payload = {
            "condition_tree": sample_rule_data["condition_tree"],
            "priority": 100,
        }
        version_response = await async_maker_client.post(
            f"/api/v1/rules/{rule_id}/versions", json=version_payload
        )
        rule_version_id = version_response.json()["rule_version_id"]

        # Submit and approve
        await async_maker_client.post(f"/api/v1/rule-versions/{rule_version_id}/submit", json={})
        await async_checker_client.post(f"/api/v1/rule-versions/{rule_version_id}/approve", json={})

        # Get rule version details
        response = await async_maker_client.get(f"/api/v1/rule-versions/{rule_version_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "APPROVED"
        assert data["approved_at"] is not None
        assert data["approved_by"] is not None


class TestListRuleVersions:
    """Tests for GET /api/v1/rules/{rule_id}/versions endpoint."""

    @pytest.mark.anyio
    async def test_should_return_all_rule_versions(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test listing all versions for a specific rule (for analyst deep links)."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create additional versions
        for i in range(2, 4):
            version_payload = {
                "condition_tree": {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 1000 * i,
                },
                "priority": 100 * i,
            }
            await async_maker_client.post(f"/api/v1/rules/{rule_id}/versions", json=version_payload)

        # List all versions
        response = await async_maker_client.get(f"/api/v1/rules/{rule_id}/versions")

        assert response.status_code == 200
        versions = response.json()
        assert len(versions) == 3  # Initial version + 2 new versions
        # Should be ordered by version descending (newest first)
        assert versions[0]["version"] == 3
        assert versions[1]["version"] == 2
        assert versions[2]["version"] == 1

    @pytest.mark.anyio
    async def test_should_return_empty_list_for_rule_with_no_versions(
        self, async_db_session: AsyncSession, async_maker_client: TestClient
    ):
        """Test listing versions for a rule that has no versions (edge case)."""
        from sqlalchemy import delete

        from app.db.models import Rule

        # Clear any existing rules
        await async_db_session.execute(delete(Rule))
        await async_db_session.commit()

        # Create a rule directly without versions (unusual but possible)
        rule = Rule(
            rule_name="Test Rule",
            rule_type="ALLOWLIST",
            current_version=0,
            status="DRAFT",
            created_by="test@example.com",
        )
        async_db_session.add(rule)
        await async_db_session.commit()

        rule_id = str(rule.rule_id)

        # List versions
        response = await async_maker_client.get(f"/api/v1/rules/{rule_id}/versions")

        assert response.status_code == 200
        versions = response.json()
        assert len(versions) == 0

    @pytest.mark.anyio
    async def test_should_return_404_for_nonexistent_rule(self, async_maker_client: TestClient):
        """Test listing versions for non-existent rule."""
        non_existent_id = str(uuid.uuid7())

        response = await async_maker_client.get(f"/api/v1/rules/{non_existent_id}/versions")

        assert response.status_code == 404


class TestGetRuleSummary:
    """Tests for GET /api/v1/rules/{rule_id}/summary endpoint."""

    @pytest.mark.anyio
    async def test_should_return_rule_summary(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test getting rule summary with latest version info."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Get summary
        response = await async_maker_client.get(f"/api/v1/rules/{rule_id}/summary")

        assert response.status_code == 200
        data = response.json()
        assert data["rule_id"] == rule_id
        assert data["rule_name"] == sample_rule_data["rule_name"]
        assert data["rule_type"] == sample_rule_data["rule_type"]
        assert data["status"] == "DRAFT"
        assert data["latest_version"] == 1
        assert data["latest_version_id"] is not None
        assert data["priority"] == 100
        assert data["action"] == "APPROVE"  # ALLOWLIST rules default to APPROVE

    @pytest.mark.anyio
    async def test_should_reflect_latest_version_after_creating_new_version(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test that summary reflects the latest version after creating new versions."""
        # Create rule
        create_response = await async_maker_client.post("/api/v1/rules", json=sample_rule_data)
        rule_id = create_response.json()["rule_id"]

        # Create new version with different priority
        version_payload = {
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 5000,
            },
            "priority": 250,
            "action": "APPROVE",
        }
        await async_maker_client.post(f"/api/v1/rules/{rule_id}/versions", json=version_payload)

        # Get summary
        response = await async_maker_client.get(f"/api/v1/rules/{rule_id}/summary")

        assert response.status_code == 200
        data = response.json()
        assert data["latest_version"] == 2
        assert data["priority"] == 250  # Should reflect latest version

    @pytest.mark.anyio
    async def test_should_return_404_for_nonexistent_rule(self, async_maker_client: TestClient):
        """Test getting summary for non-existent rule."""
        non_existent_id = str(uuid.uuid7())

        response = await async_maker_client.get(f"/api/v1/rules/{non_existent_id}/summary")

        assert response.status_code == 404


class TestSimulateRule:
    """Tests for POST /api/v1/rules/simulate endpoint."""

    @pytest.mark.anyio
    async def test_should_accept_valid_simulation_request(
        self, async_maker_client: TestClient, sample_rule_data: dict
    ):
        """Test simulation endpoint with valid request."""
        payload = {
            "rule_type": "AUTH",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "scope": {"network": ["VISA"]},
            "query": {
                "from_date": "2024-01-01T00:00:00Z",
                "to_date": "2024-01-31T23:59:59Z",
                "risk_level": "HIGH",
            },
        }

        response = await async_maker_client.post("/api/v1/rules/simulate", json=payload)

        # Should succeed (placeholder implementation returns empty results)
        assert response.status_code == 200
        data = response.json()
        assert "match_count" in data
        assert "sample_transactions" in data
        # Placeholder returns 0 matches
        assert data["match_count"] == 0
        assert data["sample_transactions"] == []

    @pytest.mark.anyio
    async def test_should_validate_condition_tree_in_simulation(
        self, async_maker_client: TestClient
    ):
        """Test that simulation endpoint validates condition tree structure."""
        # The validation only checks depth and node count, not valid type values
        # So this test uses a deeply nested tree to exceed max depth
        payload = {
            "rule_type": "AUTH",
            "condition_tree": {
                "type": "AND",
                "conditions": [
                    {
                        "type": "AND",
                        "conditions": [
                            {
                                "type": "AND",
                                "conditions": [
                                    {
                                        "type": "AND",
                                        "conditions": [
                                            {
                                                "type": "AND",
                                                "conditions": [
                                                    {
                                                        "type": "AND",
                                                        "conditions": [
                                                            {
                                                                "type": "AND",
                                                                "conditions": [
                                                                    {
                                                                        "type": "AND",
                                                                        "conditions": [
                                                                            {
                                                                                "type": "AND",
                                                                                "conditions": [
                                                                                    {
                                                                                        "type": "AND",
                                                                                        "conditions": [
                                                                                            {
                                                                                                "type": "AND",
                                                                                                "conditions": [
                                                                                                    {
                                                                                                        "type": "CONDITION",
                                                                                                        "field": "amount",
                                                                                                        "operator": "GT",
                                                                                                        "value": 100,
                                                                                                    }
                                                                                                ],
                                                                                            }
                                                                                        ],
                                                                                    }
                                                                                ],
                                                                            }
                                                                        ],
                                                                    }
                                                                ],
                                                            }
                                                        ],
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "scope": {},
            "query": {"from_date": "2024-01-01T00:00:00Z"},
        }

        response = await async_maker_client.post("/api/v1/rules/simulate", json=payload)

        # Should fail validation (exceeds max depth of 10)
        assert response.status_code in [400, 422]

    @pytest.mark.anyio
    async def test_should_require_rule_read_permission(self, client):
        """Test that authentication is required for simulation."""
        payload = {
            "rule_type": "AUTH",
            "condition_tree": {
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            "scope": {},
            "query": {},
        }

        response = await client.post("/api/v1/rules/simulate", json=payload)

        assert response.status_code == 401
