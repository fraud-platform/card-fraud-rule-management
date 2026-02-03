import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from app.core.audit import snapshot_entity
from app.db.validators import to_jsonable


class TestToJsonable:
    @pytest.mark.anyio
    async def test_primitive_types(self):
        assert to_jsonable("string") == "string"
        assert to_jsonable(42) == 42
        assert to_jsonable(3.14) == 3.14  # noqa: PLR2004
        assert to_jsonable(True)
        assert to_jsonable(None) is None

    @pytest.mark.anyio
    async def test_datetime(self):
        dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = to_jsonable(dt)
        assert result == "2023-01-01T12:00:00+00:00"

    @pytest.mark.anyio
    async def test_decimal(self):
        d = Decimal("123.456")
        result = to_jsonable(d)
        assert result == "123.456"

    @pytest.mark.anyio
    async def test_uuid(self):
        u = uuid.uuid7()
        result = to_jsonable(u)
        assert result == str(u)

    @pytest.mark.anyio
    async def test_dict(self):
        d = {"key": "value", "number": 42}
        result = to_jsonable(d)
        assert result == {"key": "value", "number": 42}

    @pytest.mark.anyio
    async def test_list(self):
        l = [1, "two", 3.0]
        result = to_jsonable(l)
        assert result == [1, "two", 3.0]

    @pytest.mark.anyio
    async def test_nested_structures(self):
        nested = {
            "datetime": datetime(2023, 1, 1, tzinfo=UTC),
            "decimal": Decimal("1.23"),
            "uuid": uuid.uuid7(),
            "list": [1, 2, {"nested": "value"}],
        }
        result = to_jsonable(nested)
        assert isinstance(result, dict)
        assert "datetime" in result
        assert "decimal" in result
        assert "uuid" in result
        assert isinstance(result["list"], list)

    @pytest.mark.anyio
    async def test_unknown_type(self):
        class CustomClass:
            def __str__(self):
                return "custom"

        obj = CustomClass()
        result = to_jsonable(obj)
        assert result == "custom"


class TestSnapshotEntity:
    @pytest.mark.anyio
    async def test_snapshot_basic_entity(self):
        class MockEntity:
            def __init__(self):
                self.id = 1
                self.name = "test"
                self.active = True

        # Mock the SQLAlchemy inspection

        mock_mapper = Mock()
        mock_attr1 = Mock()
        mock_attr1.key = "id"
        mock_attr2 = Mock()
        mock_attr2.key = "name"
        mock_attr3 = Mock()
        mock_attr3.key = "active"
        mock_mapper.column_attrs = [mock_attr1, mock_attr2, mock_attr3]

        entity = MockEntity()

        with patch("app.core.audit.inspect") as mock_inspect:
            mock_inspect.return_value.mapper = mock_mapper

            result = snapshot_entity(entity)
            assert result == {"id": 1, "name": "test", "active": True}

    @pytest.mark.anyio
    async def test_snapshot_with_include(self):
        class MockEntity:
            def __init__(self):
                self.id = 1
                self.name = "test"
                self.active = True

        mock_mapper = Mock()
        mock_attr1 = Mock()
        mock_attr1.key = "id"
        mock_attr2 = Mock()
        mock_attr2.key = "name"
        mock_attr3 = Mock()
        mock_attr3.key = "active"
        mock_mapper.column_attrs = [mock_attr1, mock_attr2, mock_attr3]

        entity = MockEntity()

        with patch("app.core.audit.inspect") as mock_inspect:
            mock_inspect.return_value.mapper = mock_mapper

            result = snapshot_entity(entity, include=["id", "name"])
            assert result == {"id": 1, "name": "test"}
            assert "active" not in result

    @pytest.mark.anyio
    async def test_snapshot_with_exclude(self):
        class MockEntity:
            def __init__(self):
                self.id = 1
                self.name = "test"
                self.active = True

        mock_mapper = Mock()
        mock_attr1 = Mock()
        mock_attr1.key = "id"
        mock_attr2 = Mock()
        mock_attr2.key = "name"
        mock_attr3 = Mock()
        mock_attr3.key = "active"
        mock_mapper.column_attrs = [mock_attr1, mock_attr2, mock_attr3]

        entity = MockEntity()

        with patch("app.core.audit.inspect") as mock_inspect:
            mock_inspect.return_value.mapper = mock_mapper

            result = snapshot_entity(entity, exclude=["active"])
            assert result == {"id": 1, "name": "test"}
            assert "active" not in result
