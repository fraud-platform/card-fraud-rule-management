import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.anyio
async def test_maker_cannot_approve_own_submission(monkeypatch):
    app = create_app()
    client = TestClient(app)

    # Override authentication dependency to simulate checker == maker
    from app.core.dependencies import get_current_user

    async def override_get_current_user():
        return {
            "sub": "maker_user",
            "permissions": ["rule:approve"],
        }

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock get_pending_approval to return an object with maker == 'maker_user'
    # The validation now happens at the repo level (rule_repo imports it)
    class DummyApproval:
        def __init__(self, maker):
            self.maker = maker

    async def fake_get_pending_approval(db, *, entity_id):
        return DummyApproval("maker_user")

    # Patch at the rule_repo module where get_pending_approval is imported and used
    monkeypatch.setattr("app.repos.rule_repo.get_pending_approval", fake_get_pending_approval)

    resp = client.post(
        "/api/v1/rule-versions/00000000-0000-0000-0000-000000000000/approve",
        json={},  # Empty body for approve request (all fields optional)
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] in ("MakerCheckerViolation", "ConflictError")
