from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.anyio
def test_list_rule_fields(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    async def fake_get_all(db: Any) -> list[dict[str, Any]]:
        return [
            {
                "field_key": "amount",
                "field_id": 3,
                "display_name": "Transaction Amount",
                "description": None,
                "data_type": "NUMBER",
                "allowed_operators": ["EQ", "GT", "LT"],
                "multi_value_allowed": False,
                "is_sensitive": False,
                "current_version": 1,
                "version": 1,
                "created_by": "system",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr("app.repos.rule_field_repo.get_all_rule_fields", fake_get_all)

    resp = client.get("/api/v1/rule-fields")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["field_key"] == "amount"


@pytest.mark.anyio
def test_list_rule_fields_with_filter(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    async def fake_get_all(db: Any) -> list[dict[str, Any]]:
        return [
            {
                "field_key": "amount",
                "field_id": 3,
                "display_name": "Transaction Amount",
                "description": None,
                "data_type": "NUMBER",
                "allowed_operators": ["EQ", "GT", "LT"],
                "multi_value_allowed": False,
                "is_sensitive": False,
                "current_version": 1,
                "version": 1,
                "created_by": "system",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr("app.repos.rule_field_repo.get_all_rule_fields", fake_get_all)

    # Query param is now ignored (is_active removed)
    resp = client.get("/api/v1/rule-fields")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1


@pytest.mark.anyio
def test_get_rule_field(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    async def fake_get_rule_field(db: Any, field_key: str) -> dict[str, Any]:
        return {
            "field_key": "amount",
            "field_id": 3,
            "display_name": "Transaction Amount",
            "description": None,
            "data_type": "NUMBER",
            "allowed_operators": ["EQ", "GT", "LT"],
            "multi_value_allowed": False,
            "is_sensitive": False,
            "current_version": 1,
            "version": 1,
            "created_by": "system",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }

    monkeypatch.setattr("app.repos.rule_field_repo.get_rule_field", fake_get_rule_field)

    resp = client.get("/api/v1/rule-fields/amount")
    assert resp.status_code == 200
    body = resp.json()
    assert body["field_key"] == "amount"


@pytest.mark.anyio
def test_create_rule_field(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {
            "sub": "admin_user",
            "permissions": ["rule_field:create"],
        }

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    # Create a mock object with attributes
    class MockField:
        def __init__(self):
            self.field_key = "new_field"
            self.field_id = 27
            self.display_name = "New Field"
            self.description = None
            self.data_type = "STRING"
            self.allowed_operators = ["EQ"]
            self.multi_value_allowed = False
            self.is_sensitive = False
            self.current_version = 1
            self.version = 1
            self.created_by = "admin_user"
            self.created_at = "2024-01-01T00:00:00Z"
            self.updated_at = "2024-01-01T00:00:00Z"

    async def fake_create_rule_field(db: Any, field: Any, created_by: str) -> MockField:
        return MockField()

    monkeypatch.setattr("app.repos.rule_field_repo.create_rule_field", fake_create_rule_field)

    payload = {
        "field_key": "new_field",
        "display_name": "New Field",
        "data_type": "STRING",
        "allowed_operators": ["EQ"],
        "multi_value_allowed": False,
        "is_sensitive": False,
    }

    resp = client.post("/api/v1/rule-fields", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["field_key"] == "new_field"


@pytest.mark.anyio
def test_update_rule_field(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {
            "sub": "admin_user",
            "permissions": ["rule_field:update"],
        }

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    # Create mock objects with attributes
    class MockField:
        def __init__(self):
            self.field_key = "amount"
            self.field_id = 3
            self.display_name = "Updated Amount"
            self.description = None
            self.data_type = "NUMBER"
            self.allowed_operators = ["EQ", "GT", "LT"]
            self.multi_value_allowed = False
            self.is_sensitive = False
            self.current_version = 1
            self.version = 1
            self.created_by = "system"
            self.created_at = "2024-01-01T00:00:00Z"
            self.updated_at = "2024-01-01T00:00:00Z"

    async def fake_get_rule_field(db: Any, field_key: str) -> MockField:
        f = MockField()
        f.display_name = "Transaction Amount"
        return f

    async def fake_update_rule_field(db: Any, field_key: str, updates: dict[str, Any]) -> MockField:
        return MockField()

    monkeypatch.setattr("app.repos.rule_field_repo.get_rule_field", fake_get_rule_field)
    monkeypatch.setattr("app.repos.rule_field_repo.update_rule_field", fake_update_rule_field)

    payload = {"display_name": "Updated Amount"}

    resp = client.patch("/api/v1/rule-fields/amount", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Updated Amount"


@pytest.mark.anyio
def test_get_field_metadata(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    async def fake_get_field_metadata(db: Any, field_key: str) -> list[dict[str, Any]]:
        return [
            {
                "field_key": "amount",
                "meta_key": "validation",
                "meta_value": {"min": 0, "max": 10000},
                "description": None,
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr("app.repos.rule_field_repo.get_field_metadata", fake_get_field_metadata)

    resp = client.get("/api/v1/rule-fields/amount/metadata")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["meta_key"] == "validation"


@pytest.mark.anyio
def test_get_specific_metadata(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {"sub": "test_user"}

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    async def fake_get_specific_metadata(db: Any, field_key: str, meta_key: str) -> dict[str, Any]:
        return {
            "field_key": "amount",
            "meta_key": "validation",
            "meta_value": {"min": 0, "max": 10000},
            "description": None,
            "created_at": "2024-01-01T00:00:00Z",
        }

    monkeypatch.setattr(
        "app.repos.rule_field_repo.get_specific_metadata", fake_get_specific_metadata
    )

    resp = client.get("/api/v1/rule-fields/amount/metadata/validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta_key"] == "validation"


@pytest.mark.anyio
def test_upsert_metadata_create(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {
            "sub": "admin_user",
            "permissions": ["rule_field:update"],
        }

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    async def fake_get_specific_metadata(db: Any, field_key: str, meta_key: str) -> None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Not found")

    # Create mock object with attributes
    class MockMetadata:
        def __init__(self):
            self.field_key = "amount"
            self.meta_key = "validation"
            self.meta_value = {"min": 0, "max": 10000}
            self.description = None
            self.created_at = "2024-01-01T00:00:00Z"

    async def fake_upsert_field_metadata(
        db: Any, field_key: str, meta_key: str, meta_value: dict[str, Any]
    ) -> MockMetadata:
        return MockMetadata()

    monkeypatch.setattr(
        "app.repos.rule_field_repo.get_specific_metadata", fake_get_specific_metadata
    )
    monkeypatch.setattr(
        "app.repos.rule_field_repo.upsert_field_metadata", fake_upsert_field_metadata
    )

    payload = {"meta_value": {"min": 0, "max": 10000}}

    resp = client.put("/api/v1/rule-fields/amount/metadata/validation", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta_key"] == "validation"


@pytest.mark.anyio
def test_upsert_metadata_update(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {
            "sub": "admin_user",
            "permissions": ["rule_field:update"],
        }

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    # Create mock object with attributes
    class MockMetadata:
        def __init__(self):
            self.field_key = "amount"
            self.meta_key = "validation"
            self.meta_value = {"min": 0, "max": 10000}
            self.description = None
            self.created_at = "2024-01-01T00:00:00Z"

    async def fake_get_specific_metadata(db: Any, field_key: str, meta_key: str) -> MockMetadata:
        return MockMetadata()

    async def fake_upsert_field_metadata(
        db: Any, field_key: str, meta_key: str, meta_value: dict[str, Any]
    ) -> MockMetadata:
        return MockMetadata()

    monkeypatch.setattr(
        "app.repos.rule_field_repo.get_specific_metadata", fake_get_specific_metadata
    )
    monkeypatch.setattr(
        "app.repos.rule_field_repo.upsert_field_metadata", fake_upsert_field_metadata
    )

    payload = {"meta_value": {"min": 0, "max": 10000}}

    resp = client.put("/api/v1/rule-fields/amount/metadata/validation", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta_value"]["min"] == 0


@pytest.mark.anyio
def test_delete_metadata(monkeypatch: pytest.MonkeyPatch):
    app = create_app()
    client = TestClient(app)

    from app.core.dependencies import get_current_user

    def override_get_current_user():
        return {
            "sub": "admin_user",
            "permissions": ["rule_field:delete"],
        }

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock async database session
    mock_db = AsyncMock()
    # SQLAlchemy AsyncSession methods that are actually synchronous
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()
    mock_db.flush = AsyncMock()

    def fake_get_async_db_session():
        yield mock_db

    from app.core.dependencies import get_async_db_session

    app.dependency_overrides[get_async_db_session] = fake_get_async_db_session

    # Create mock object with attributes
    class MockMetadata:
        def __init__(self):
            self.field_key = "amount"
            self.meta_key = "validation"
            self.meta_value = {"min": 0, "max": 10000}
            self.description = None
            self.created_at = "2024-01-01T00:00:00Z"

    async def fake_get_specific_metadata(db: Any, field_key: str, meta_key: str) -> MockMetadata:
        return MockMetadata()

    async def fake_delete_field_metadata(db: Any, field_key: str, meta_key: str) -> None:
        pass  # Mock implementation

    monkeypatch.setattr(
        "app.repos.rule_field_repo.get_specific_metadata", fake_get_specific_metadata
    )
    monkeypatch.setattr(
        "app.repos.rule_field_repo.delete_field_metadata", fake_delete_field_metadata
    )

    resp = client.delete("/api/v1/rule-fields/amount/metadata/validation")
    assert resp.status_code == 204
