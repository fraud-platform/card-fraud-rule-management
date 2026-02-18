import pytest


@pytest.mark.smoke
@pytest.mark.anyio
async def test_submit_creates_pending_approval_and_audit(maker_client, admin_client):
    # Create rule
    payload = {
        "rule_name": "Approval Flow Rule",
        "description": "Test",
        "rule_type": "ALLOWLIST",
        "condition_tree": {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 1},
        "priority": 100,
    }

    create_resp = await maker_client.post("/api/v1/rules", json=payload)
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["rule_id"]

    # Create new version
    version_payload = {"condition_tree": payload["condition_tree"], "priority": 100}
    version_resp = await maker_client.post(
        f"/api/v1/rules/{rule_id}/versions", json=version_payload
    )
    assert version_resp.status_code == 201
    version_id = version_resp.json()["rule_version_id"]

    # Submit for approval
    submit_resp = await maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})
    assert submit_resp.status_code == 200

    # Check approvals list contains pending approval
    ap_resp = await maker_client.get("/api/v1/approvals")
    assert ap_resp.status_code == 200
    approvals_data = ap_resp.json()
    approvals = approvals_data["items"]
    assert any(
        a
        for a in approvals
        if str(a["entity_id"]) == version_id
        and a["status"] == "PENDING"
        and a["maker"] == "maker-123"
    )


@pytest.mark.smoke
@pytest.mark.anyio
async def test_approve_and_reject_flow(maker_client, checker_client, admin_client):
    # Create rule and version, submit
    payload = {
        "rule_name": "Approval Flow Rule 2",
        "description": "Test",
        "rule_type": "ALLOWLIST",
        "condition_tree": {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 1},
        "priority": 100,
    }

    create_resp = await maker_client.post("/api/v1/rules", json=payload)
    rule_id = create_resp.json()["rule_id"]

    version_payload = {"condition_tree": payload["condition_tree"], "priority": 100}
    version_resp = await maker_client.post(
        f"/api/v1/rules/{rule_id}/versions", json=version_payload
    )
    version_id = version_resp.json()["rule_version_id"]

    await maker_client.post(f"/api/v1/rule-versions/{version_id}/submit", json={})

    # Approve as checker
    approve_resp = await checker_client.post(f"/api/v1/rule-versions/{version_id}/approve", json={})
    assert approve_resp.status_code == 200
    approved = approve_resp.json()
    assert approved["status"] == "APPROVED"

    # Check approval row updated
    ap_resp = await checker_client.get("/api/v1/approvals")
    approvals_data = ap_resp.json()
    approvals = approvals_data["items"]
    assert any(
        a
        for a in approvals
        if str(a["entity_id"]) == version_id
        and a["status"] == "APPROVED"
        and a.get("checker") == "checker-123"
    )

    # Check audit log for APPROVE (admin view)
    audit_resp = await admin_client.get("/api/v1/audit-log?action=APPROVE&entity_type=RULE_VERSION")
    audits_data = audit_resp.json()
    audits = audits_data["items"]
    assert any(a for a in audits if str(a["entity_id"]) == version_id and a["action"] == "APPROVE")

    # Now create another version and submit then reject
    version_resp2 = await maker_client.post(
        f"/api/v1/rules/{rule_id}/versions", json=version_payload
    )
    version2 = version_resp2.json()["rule_version_id"]
    await maker_client.post(f"/api/v1/rule-versions/{version2}/submit", json={})

    reject_resp = await checker_client.post(f"/api/v1/rule-versions/{version2}/reject", json={})
    assert reject_resp.status_code == 200
    rejected = reject_resp.json()
    assert rejected["status"] == "REJECTED"

    # Check audit log for REJECT
    audit_reject_data = (
        await checker_client.get("/api/v1/audit-log?action=REJECT&entity_type=RULE_VERSION")
    ).json()
    audit_reject = audit_reject_data["items"]
    assert any(
        a
        for a in audit_reject
        if str(a["entity_id"]) == version2
        and a["action"] == "REJECT"
        and a["performed_by"] == "checker-123"
    )
