import pytest


@pytest.mark.anyio
async def test_create_update_field_and_audit(admin_client, async_db_session):
    """Create a rule field as ADMIN, update it, and assert audit log entries were created."""
    payload = {
        "field_key": "it_test_field",
        "display_name": "IT Test Field",
        "data_type": "STRING",
        "allowed_operators": ["EQ", "IN"],
        "multi_value_allowed": False,
        "is_sensitive": False,
        "is_active": True,
    }

    # Create
    resp = admin_client.post("/api/v1/rule-fields", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["field_key"] == "it_test_field"

    # Retrieve
    get_resp = admin_client.get(f"/api/v1/rule-fields/{data['field_key']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["display_name"] == "IT Test Field"

    # Update display_name
    patch = {"display_name": "IT Test Field - Updated"}
    patch_resp = admin_client.patch(f"/api/v1/rule-fields/{data['field_key']}", json=patch)
    assert patch_resp.status_code == 200

    # Verify audit log for CREATE
    logs_create_data = admin_client.get(
        "/api/v1/audit-log?action=CREATE&entity_type=RULE_FIELD"
    ).json()
    logs_create = logs_create_data["items"]
    assert any(
        (
            l.get("new_value")
            and l["new_value"].get("field_key") == data["field_key"]
            and l["performed_by"] == "admin-123"
        )
        for l in logs_create
    ), "Expected CREATE audit log entry not found"

    # Verify audit log for UPDATE contains the old/new display_name
    logs_update_data = admin_client.get(
        "/api/v1/audit-log?action=UPDATE&entity_type=RULE_FIELD"
    ).json()
    logs_update = logs_update_data["items"]
    assert any(
        (
            l.get("old_value")
            and l.get("new_value")
            and l["old_value"].get("display_name") == "IT Test Field"
            and l["new_value"].get("display_name") == "IT Test Field - Updated"
        )
        for l in logs_update
    ), "Expected UPDATE audit log entry not found"
