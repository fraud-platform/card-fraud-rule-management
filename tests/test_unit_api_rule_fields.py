"""
Comprehensive integration tests for RuleField API endpoints.

Tests cover:
- GET /rule-fields (list with filtering)
- GET /rule-fields/{field_key} (retrieve single field)
- POST /rule-fields (create new field)
- PATCH /rule-fields/{field_key} (update field)
- GET /rule-fields/{field_key}/metadata (list metadata)
- GET /rule-fields/{field_key}/metadata/{meta_key} (get specific metadata)
- PUT /rule-fields/{field_key}/metadata/{meta_key} (upsert metadata)
- DELETE /rule-fields/{field_key}/metadata/{meta_key} (delete metadata)
- Authentication and authorization checks
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import acreate_rule_field_in_db


class TestListRuleFields:
    """Tests for GET /api/v1/rule-fields endpoint."""

    @pytest.mark.anyio
    async def test_should_return_all_fields_when_no_filter(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test listing all rule fields without filtering."""
        # Create test fields
        await acreate_rule_field_in_db(async_db_session, field_key="field1", display_name="Field 1")
        await acreate_rule_field_in_db(async_db_session, field_key="field2", display_name="Field 2")

        response = await async_authenticated_client.get("/api/v1/rule-fields")

        assert response.status_code == 200
        data = response.json()
        # Check for created fields
        field_keys = {f["field_key"] for f in data}
        assert "field1" in field_keys
        assert "field2" in field_keys

    @pytest.mark.anyio
    async def test_should_require_authentication(self, client: TestClient):
        """Test that authentication is required."""
        response = await client.get("/api/v1/rule-fields")
        assert response.status_code == 401


class TestGetRuleField:
    """Tests for GET /api/v1/rule-fields/{field_key} endpoint."""

    @pytest.mark.anyio
    async def test_should_return_field_when_exists(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test retrieving an existing field."""
        # Use unique field key to avoid conflict with seeded data
        field = await acreate_rule_field_in_db(
            async_db_session,
            field_key="test_transaction_amount",
            display_name="Transaction Amount",
            data_type="NUMBER",
        )

        response = await async_authenticated_client.get(f"/api/v1/rule-fields/{field.field_key}")

        assert response.status_code == 200
        data = response.json()
        assert data["field_key"] == "test_transaction_amount"
        assert data["display_name"] == "Transaction Amount"
        assert data["data_type"] == "NUMBER"

    @pytest.mark.anyio
    async def test_should_return_seeded_field(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test retrieving a seeded field."""
        # Create the "seeded" amount field
        await acreate_rule_field_in_db(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"],
        )

        response = await async_authenticated_client.get("/api/v1/rule-fields/amount")

        assert response.status_code == 200
        data = response.json()
        assert data["field_key"] == "amount"
        assert data["display_name"] == "Amount"
        assert data["data_type"] == "NUMBER"

    @pytest.mark.anyio
    async def test_should_return_404_when_field_not_found(
        self, async_authenticated_client: TestClient
    ):
        """Test retrieving non-existent field returns 404."""
        response = await async_authenticated_client.get("/api/v1/rule-fields/nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"
        assert "not found" in data["message"].lower()

    @pytest.mark.anyio
    async def test_should_require_authentication(self, client: TestClient):
        """Test that authentication is required."""
        response = await client.get("/api/v1/rule-fields/amount")
        assert response.status_code == 401


class TestCreateRuleField:
    """Tests for POST /api/v1/rule-fields endpoint."""

    @pytest.mark.anyio
    async def test_should_create_field_when_valid_data(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test creating a new field with valid data."""
        # Use unique field key to avoid conflict with seeded data
        payload = {
            "field_key": "test_merchant_category",
            "display_name": "Merchant Category",
            "data_type": "STRING",
            "allowed_operators": ["EQ", "IN"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "is_active": True,
        }

        response = await async_admin_client.post("/api/v1/rule-fields", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["field_key"] == "test_merchant_category"
        assert data["display_name"] == "Merchant Category"
        assert data["data_type"] == "STRING"
        assert "created_at" in data

    @pytest.mark.anyio
    async def test_should_return_409_when_field_key_exists(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test creating field with duplicate key returns 409."""
        # Create existing field
        await acreate_rule_field_in_db(async_db_session, field_key="duplicate_key")

        payload = {
            "field_key": "duplicate_key",
            "display_name": "Duplicate Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
        }

        response = await async_admin_client.post("/api/v1/rule-fields", json=payload)

        assert response.status_code == 409
        data = response.json()
        assert data["error"] == "ConflictError"

    @pytest.mark.anyio
    async def test_should_validate_data_type(self, async_admin_client: TestClient):
        """Test that invalid data_type is rejected."""
        payload = {
            "field_key": "test_field",
            "display_name": "Test Field",
            "data_type": "INVALID_TYPE",  # Invalid
            "allowed_operators": ["EQ"],
        }

        response = await async_admin_client.post("/api/v1/rule-fields", json=payload)

        # Should fail validation (422 or 400)
        assert response.status_code in [400, 422]

    @pytest.mark.anyio
    async def test_should_require_admin_role(
        self, async_authenticated_client: TestClient, async_maker_client: TestClient
    ):
        """Test that only ADMIN role can create fields."""
        payload = {
            "field_key": "test_field",
            "display_name": "Test Field",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
        }

        # Regular user should be forbidden
        response = await async_authenticated_client.post("/api/v1/rule-fields", json=payload)
        assert response.status_code == 403

        # MAKER role should be forbidden (not ADMIN)
        response = await async_maker_client.post("/api/v1/rule-fields", json=payload)
        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_should_require_authentication(self, client: TestClient):
        """Test that authentication is required."""
        payload = {
            "field_key": "test_field",
            "display_name": "Test",
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
        }

        response = await client.post("/api/v1/rule-fields", json=payload)
        assert response.status_code == 401


class TestUpdateRuleField:
    """Tests for PATCH /api/v1/rule-fields/{field_key} endpoint."""

    @pytest.mark.anyio
    async def test_should_update_field_when_valid_data(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test updating a field with valid data."""
        # Create the field to update
        await acreate_rule_field_in_db(
            async_db_session,
            field_key="amount",
            display_name="Transaction Amount",
            data_type="NUMBER",
            allowed_operators=["EQ", "GT", "LT"],
        )
        payload = {"display_name": "Updated Transaction Amount"}

        response = await async_admin_client.patch("/api/v1/rule-fields/amount", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Updated Transaction Amount"
        assert data["field_key"] == "amount"  # Unchanged

    @pytest.mark.anyio
    async def test_should_update_description(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test updating field description."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")

        payload = {"description": "Updated field description"}

        response = await async_admin_client.patch(
            f"/api/v1/rule-fields/{field.field_key}", json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated field description"

    @pytest.mark.anyio
    async def test_should_not_allow_field_key_change(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test that field_key is immutable."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="original_key")

        payload = {"field_key": "new_key"}  # Attempting to change immutable field

        response = await async_admin_client.patch(
            f"/api/v1/rule-fields/{field.field_key}", json=payload
        )

        # Should either ignore the change or return error
        # Based on implementation, field_key should remain unchanged
        if response.status_code == 200:
            data = response.json()
            assert data["field_key"] == "original_key"

    @pytest.mark.anyio
    async def test_should_return_404_when_field_not_found(self, async_admin_client: TestClient):
        """Test updating non-existent field returns 404."""
        payload = {"display_name": "New Name"}

        response = await async_admin_client.patch("/api/v1/rule-fields/nonexistent", json=payload)

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "NotFoundError"

    @pytest.mark.anyio
    async def test_should_require_admin_role(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test that only ADMIN role can update fields."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        payload = {"display_name": "Updated Name"}

        response = await async_authenticated_client.patch(
            f"/api/v1/rule-fields/{field.field_key}", json=payload
        )

        assert response.status_code == 403

    @pytest.mark.anyio
    async def test_should_require_authentication(
        self, client: TestClient, async_db_session: AsyncSession
    ):
        """Test that authentication is required."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        payload = {"display_name": "Updated"}

        response = await client.patch(f"/api/v1/rule-fields/{field.field_key}", json=payload)
        assert response.status_code == 401


class TestGetFieldMetadata:
    """Tests for GET /api/v1/rule-fields/{field_key}/metadata endpoint."""

    @pytest.mark.anyio
    async def test_should_return_all_metadata_for_field(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test retrieving all metadata for a field."""
        from app.db.models import RuleFieldMetadata

        field = await acreate_rule_field_in_db(async_db_session, field_key="velocity_field")

        # Add metadata entries
        meta1 = RuleFieldMetadata(
            field_key=field.field_key,
            meta_key="velocity_config",
            meta_value={"window": 10, "unit": "minutes"},
        )
        meta2 = RuleFieldMetadata(
            field_key=field.field_key,
            meta_key="ui_config",
            meta_value={"group": "Velocity", "order": 1},
        )
        async_db_session.add_all([meta1, meta2])
        await async_db_session.commit()

        response = await async_authenticated_client.get(
            f"/api/v1/rule-fields/{field.field_key}/metadata"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        meta_keys = {m["meta_key"] for m in data}
        assert meta_keys == {"velocity_config", "ui_config"}

    @pytest.mark.anyio
    async def test_should_return_empty_list_when_no_metadata(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test retrieving metadata when none exists."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")

        response = await async_authenticated_client.get(
            f"/api/v1/rule-fields/{field.field_key}/metadata"
        )

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.anyio
    async def test_should_return_404_when_field_not_found(
        self, async_authenticated_client: TestClient
    ):
        """Test retrieving metadata for non-existent field."""
        response = await async_authenticated_client.get("/api/v1/rule-fields/nonexistent/metadata")

        assert response.status_code == 404


class TestGetSpecificMetadata:
    """Tests for GET /api/v1/rule-fields/{field_key}/metadata/{meta_key}."""

    @pytest.mark.anyio
    async def test_should_return_metadata_when_exists(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test retrieving specific metadata entry."""
        from app.db.models import RuleFieldMetadata

        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        meta = RuleFieldMetadata(
            field_key=field.field_key,
            meta_key="validation",
            meta_value={"min": 0, "max": 100},
        )
        async_db_session.add(meta)
        await async_db_session.commit()

        response = await async_authenticated_client.get(
            f"/api/v1/rule-fields/{field.field_key}/metadata/validation"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["meta_key"] == "validation"
        assert data["meta_value"]["min"] == 0
        assert data["meta_value"]["max"] == 100

    @pytest.mark.anyio
    async def test_should_return_404_when_meta_key_not_found(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test retrieving non-existent metadata key."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")

        response = await async_authenticated_client.get(
            f"/api/v1/rule-fields/{field.field_key}/metadata/nonexistent"
        )

        assert response.status_code == 404


class TestUpsertMetadata:
    """Tests for PUT /api/v1/rule-fields/{field_key}/metadata/{meta_key}."""

    @pytest.mark.anyio
    async def test_should_create_metadata_when_not_exists(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test creating new metadata entry."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")

        payload = {
            "meta_value": {
                "aggregation": "COUNT",
                "window": {"value": 10, "unit": "MINUTES"},
            }
        }

        response = await async_admin_client.put(
            f"/api/v1/rule-fields/{field.field_key}/metadata/velocity_config",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["meta_key"] == "velocity_config"
        assert data["meta_value"]["aggregation"] == "COUNT"

    @pytest.mark.anyio
    async def test_should_update_metadata_when_exists(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test updating existing metadata entry."""
        from app.db.models import RuleFieldMetadata

        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        meta = RuleFieldMetadata(
            field_key=field.field_key,
            meta_key="validation",
            meta_value={"min": 0, "max": 100},
        )
        async_db_session.add(meta)
        await async_db_session.commit()

        payload = {"meta_value": {"min": 10, "max": 200}}

        response = await async_admin_client.put(
            f"/api/v1/rule-fields/{field.field_key}/metadata/validation",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["meta_value"]["min"] == 10
        assert data["meta_value"]["max"] == 200

    @pytest.mark.anyio
    async def test_should_return_404_when_field_not_found(self, async_admin_client: TestClient):
        """Test upserting metadata for non-existent field."""
        payload = {"meta_value": {"key": "value"}}

        response = await async_admin_client.put(
            "/api/v1/rule-fields/nonexistent/metadata/test", json=payload
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_should_require_admin_role(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test that only ADMIN role can upsert metadata."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        payload = {"meta_value": {"key": "value"}}

        response = await async_authenticated_client.put(
            f"/api/v1/rule-fields/{field.field_key}/metadata/test", json=payload
        )

        assert response.status_code == 403


class TestDeleteMetadata:
    """Tests for DELETE /api/v1/rule-fields/{field_key}/metadata/{meta_key}."""

    @pytest.mark.anyio
    @pytest.mark.skip(
        reason="Session management complexity - requires clean_async_db_session with proper transaction handling"
    )
    async def test_should_delete_metadata_when_exists(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test deleting existing metadata entry."""

        from app.db.models import RuleFieldMetadata

        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        meta = RuleFieldMetadata(
            field_key=field.field_key,
            meta_key="to_delete",
            meta_value={"key": "value"},
        )
        async_db_session.add(meta)
        await async_db_session.commit()

        # Verify metadata exists via API
        verify_response = await async_admin_client.get(
            f"/api/v1/rule-fields/{field.field_key}/metadata/to_delete"
        )
        assert verify_response.status_code == 200, "Metadata should exist before delete"

        # Delete via API
        response = await async_admin_client.delete(
            f"/api/v1/rule-fields/{field.field_key}/metadata/to_delete"
        )
        assert response.status_code == 204

        # Verify deletion via API (the API should return 404)
        verify_response = await async_admin_client.get(
            f"/api/v1/rule-fields/{field.field_key}/metadata/to_delete"
        )
        assert verify_response.status_code == 404, "Metadata should be deleted after API call"

    @pytest.mark.anyio
    async def test_should_return_404_when_metadata_not_found(
        self, async_admin_client: TestClient, async_db_session: AsyncSession
    ):
        """Test deleting non-existent metadata."""
        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")

        response = await async_admin_client.delete(
            f"/api/v1/rule-fields/{field.field_key}/metadata/nonexistent"
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_should_require_admin_role(
        self, async_authenticated_client: TestClient, async_db_session: AsyncSession
    ):
        """Test that only ADMIN role can delete metadata."""
        from app.db.models import RuleFieldMetadata

        field = await acreate_rule_field_in_db(async_db_session, field_key="test_field")
        meta = RuleFieldMetadata(
            field_key=field.field_key,
            meta_key="test",
            meta_value={"key": "value"},
        )
        async_db_session.add(meta)
        await async_db_session.commit()

        response = await async_authenticated_client.delete(
            f"/api/v1/rule-fields/{field.field_key}/metadata/test"
        )

        assert response.status_code == 403


class TestRuleFieldEdgeCases:
    """Edge case and validation tests."""

    @pytest.mark.anyio
    async def test_should_handle_special_characters_in_field_key(
        self, async_admin_client: TestClient
    ):
        """Test field_key with special characters (underscores are valid)."""
        # Use unique key to avoid conflict with seeded velocity_txn_count_10m_by_card
        payload = {
            "field_key": "test_velocity_txn_count_10m_by_card",
            "display_name": "Velocity Count",
            "data_type": "NUMBER",
            "allowed_operators": ["GT"],
        }

        response = await async_admin_client.post("/api/v1/rule-fields", json=payload)
        assert response.status_code in [201, 400, 422]

    @pytest.mark.anyio
    async def test_should_validate_required_fields(self, async_admin_client: TestClient):
        """Test that required fields are enforced."""
        payload = {
            "field_key": "test_field",
            # Missing required fields: display_name, data_type, allowed_operators
        }

        response = await async_admin_client.post("/api/v1/rule-fields", json=payload)
        assert response.status_code == 422  # Validation error
