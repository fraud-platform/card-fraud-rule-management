import os

import pytest

# Ensure required settings exist for tests that import app
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL_APP", "postgresql://user:pass@localhost:5432/db")
os.environ.setdefault("AUTH0_DOMAIN", "example.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://fraud-governance-api")

from datetime import UTC

from app.main import create_app


@pytest.mark.anyio
async def test_get_approvals_and_audit_log(monkeypatch):
    app = create_app()

    # Add authentication override for read endpoints
    from app.core.security import get_current_user

    async def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)

    # Fake approval objects
    class DummyApproval:
        def __init__(self):
            from datetime import datetime
            from uuid import UUID

            self.approval_id = UUID(int=0)
            self.entity_type = "RULE_VERSION"
            self.entity_id = UUID(int=0)
            self.action = "SUBMIT"
            self.maker = "maker_user"
            self.checker = None
            self.status = "PENDING"
            self.remarks = None
            self.created_at = datetime.now()
            self.decided_at = None

    class DummyAudit:
        def __init__(self):
            from datetime import datetime
            from uuid import UUID

            self.audit_id = UUID(int=0)
            self.entity_type = "RULE_VERSION"
            self.entity_id = UUID(int=0)
            self.action = "APPROVE"
            self.old_value = None
            self.new_value = {"status": "APPROVED"}
            self.performed_by = "checker_user"
            self.performed_at = datetime.now()

    async def fake_list_approvals_tuple(
        db, *, status=None, entity_type=None, cursor=None, limit=50, direction="next"
    ):
        dummy = DummyApproval()
        return (
            [
                {
                    "approval_id": dummy.approval_id,
                    "entity_type": dummy.entity_type,
                    "entity_id": dummy.entity_id,
                    "action": dummy.action,
                    "maker": dummy.maker,
                    "checker": dummy.checker,
                    "status": dummy.status,
                    "remarks": dummy.remarks,
                    "created_at": dummy.created_at,
                    "decided_at": dummy.decided_at,
                }
            ],
            False,  # has_next
            False,  # has_prev
            None,  # next_cursor
            None,  # prev_cursor
        )

    async def fake_list_audit_logs_tuple(
        db,
        *,
        entity_type=None,
        entity_id=None,
        action=None,
        performed_by=None,
        since=None,
        until=None,
        cursor=None,
        limit=100,
        direction="next",
    ):
        return (
            [DummyAudit()],
            False,  # has_next
            False,  # has_prev
            None,  # next_cursor
            None,  # prev_cursor
        )

    monkeypatch.setattr("app.api.routes.approvals.list_approvals", fake_list_approvals_tuple)
    monkeypatch.setattr("app.api.routes.approvals.list_audit_logs", fake_list_audit_logs_tuple)

    resp = client.get("/api/v1/approvals")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)

    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.anyio
async def test_audit_log_filters_pass_through(monkeypatch):
    app = create_app()

    # Add authentication override for read endpoints
    from app.core.security import get_current_user

    async def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)

    called: dict = {}

    class DummyAudit:
        def __init__(self):
            from datetime import datetime
            from uuid import UUID

            self.audit_id = UUID(int=0)
            self.entity_type = "RULESET"
            self.entity_id = UUID(int=0)
            self.action = "COMPILE"
            self.old_value = None
            self.new_value = {"compiled_ast": {"rules": []}}
            self.performed_by = "checker_user"
            self.performed_at = datetime.now()

    async def fake_list_audit_logs(
        db,
        *,
        entity_type=None,
        entity_id=None,
        action=None,
        performed_by=None,
        since=None,
        until=None,
        cursor=None,
        limit=100,
        direction="next",
    ):
        called.update(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "performed_by": performed_by,
                "since": since,
                "until": until,
                "limit": limit,
                "cursor": cursor,
                "direction": direction,
            }
        )
        return (
            [DummyAudit()],
            False,  # has_next
            False,  # has_prev
            None,  # next_cursor
            None,  # prev_cursor
        )

    monkeypatch.setattr("app.api.routes.approvals.list_audit_logs", fake_list_audit_logs)

    resp = client.get(
        "/api/v1/audit-log",
        params={
            "entity_type": "RULESET",
            "entity_id": "00000000-0000-0000-0000-000000000000",
            "action": "COMPILE",
            "performed_by": "checker_user",
            "since": "2026-01-01T00:00:00Z",
            "until": "2026-01-02T00:00:00Z",
            "limit": 10,
        },
    )
    assert resp.status_code == 200

    # Verify all filters were passed through
    assert called["entity_type"] == "RULESET"
    assert called["action"] == "COMPILE"
    assert called["performed_by"] == "checker_user"
    # FastAPI parses date strings to datetime objects
    from datetime import datetime

    expected_since = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    expected_until = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    assert called["since"] == expected_since
    assert called["until"] == expected_until
    assert called["limit"] == 10
