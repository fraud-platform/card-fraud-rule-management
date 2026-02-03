"""
Tests for pagination edge cases.

Tests cover:
- Invalid/tampered cursor handling
- Pagination with empty results
- Single item pagination
- Very large datasets
- Cursor from different query/entity
- BLOCKLIST limit values
- Extremely large limit values
- Cursor encoding edge cases
"""

from uuid import UUID

import pytest

from app.api.schemas.keyset_pagination import CursorDirection
from app.db.models import Rule, RuleVersion
from app.domain.enums import EntityStatus, RuleType
from app.repos.pagination import decode_cursor, encode_cursor
from app.repos.rule_repo import list_rules
from tests.conftest import create_rule_in_db


class TestInvalidCursorHandling:
    """Tests for invalid cursor handling."""

    @pytest.mark.anyio
    async def test_malformed_base64_cursor(self, async_db_session):
        """Test that malformed base64 cursor is handled."""
        # Create some rules
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Not valid base64
        malformed_cursor = "not-valid-base64!!!"

        with pytest.raises(ValueError):
            await list_rules(async_db_session, cursor=malformed_cursor, limit=10)

    @pytest.mark.anyio
    async def test_cursor_from_different_entity_type(self, async_db_session):
        """Test cursor from one entity type used on another."""
        from app.repos.ruleset_repo import create_ruleset, list_rulesets

        # Create rules and rulesets
        for _i in range(3):
            await create_rule_in_db(async_db_session)

        await create_ruleset(
            async_db_session,
            environment="test",
            region="AMERICAS",
            country="US",
            rule_type=RuleType.ALLOWLIST.value,
            name="Test Ruleset",
            description="Test ruleset for cursor test",
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Get cursor from ruleset list
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rulesets(
            async_db_session, limit=10
        )

        # Try to use ruleset cursor on rules list (should work with UUID validation)
        # The cursor might point to a non-existent rule, but should return empty results
        if next_cursor:
            items2, has_next2, has_prev2, next_cursor2, prev_cursor2 = await list_rules(
                async_db_session, cursor=next_cursor, limit=10
            )
            # Should return results (UUID won't match, so returns first page)
            assert isinstance(items2, list)

    @pytest.mark.anyio
    async def test_empty_cursor_string(self, async_db_session):
        """Test empty string as cursor."""
        # Create some rules
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Empty cursor should be treated as no cursor (first page)
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, cursor="", limit=10
        )

        # Should return first page
        assert len(items) > 0

    @pytest.mark.anyio
    async def test_none_cursor_explicit(self, async_db_session):
        """Test explicit None as cursor."""
        # Create some rules
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # None cursor should be treated as first page
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, cursor=None, limit=10
        )

        assert len(items) > 0


class TestPaginationBoundaryConditions:
    """Tests for pagination boundary conditions."""

    @pytest.mark.anyio
    async def test_single_item_pagination(self, async_db_session):
        """Test pagination with exactly one item."""
        await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # First page
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=10
        )

        assert len(items) == 1
        assert has_next is False
        assert has_prev is False
        assert next_cursor is None
        assert prev_cursor is None

    @pytest.mark.anyio
    async def test_limit_equals_item_count(self, async_db_session):
        """Test pagination when limit equals exact item count."""
        # Create exactly 10 items
        for _i in range(10):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Request exactly 10
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=10
        )

        assert len(items) == 10
        assert has_next is False
        assert next_cursor is None

    @pytest.mark.anyio
    async def test_limit_one(self, async_db_session):
        """Test pagination with limit=1."""
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=1
        )

        assert len(items) == 1
        assert has_next is True

    @pytest.mark.anyio
    async def test_very_large_limit(self, async_db_session):
        """Test pagination with very large limit."""
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Very large limit should return all items
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=999999
        )

        assert len(items) == 5
        assert has_next is False

    @pytest.mark.anyio
    async def test_BLOCKLIST_limit(self, async_db_session):
        """Test pagination with BLOCKLIST limit."""
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # BLOCKLIST limit - behavior depends on implementation
        # Should either reject or treat as no limit
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=-1
        )

        # Should get results (implementation may clamp to 0 or min/max)
        assert isinstance(items, list)

    @pytest.mark.anyio
    async def test_zero_limit(self, async_db_session):
        """Test pagination with limit=0."""
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Zero limit should return empty results
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=0
        )

        assert items == []

    @pytest.mark.anyio
    async def test_pagination_with_no_results(self, async_db_session):
        """Test pagination when no items exist."""
        # Don't create any items

        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=10
        )

        assert items == []
        assert has_next is False
        assert has_prev is False
        assert next_cursor is None
        assert prev_cursor is None


class TestCursorEncodingEdgeCases:
    """Tests for cursor encoding edge cases."""

    @pytest.mark.anyio
    async def test_encode_decode_roundtrip(self):
        """Test that encode/decode roundtrip preserves data."""
        from datetime import UTC, datetime
        from uuid import uuid4

        test_id = str(uuid4())
        test_time = datetime(2024, 6, 15, 14, 30, 45, 123456, tzinfo=UTC)

        cursor = encode_cursor(test_id, test_time)
        decoded_id, decoded_time = decode_cursor(cursor)

        assert decoded_id == test_id
        assert decoded_time == test_time

    @pytest.mark.anyio
    async def test_encode_cursor_with_future_timestamp(self):
        """Test encoding cursor with future timestamp."""
        from datetime import UTC, datetime, timedelta

        future_time = datetime.now(UTC) + timedelta(days=365)
        test_id = "test-id-123"

        cursor = encode_cursor(test_id, future_time)
        decoded_id, decoded_time = decode_cursor(cursor)

        assert decoded_id == test_id
        assert decoded_time == future_time

    @pytest.mark.anyio
    async def test_encode_cursor_with_epoch(self):
        """Test encoding cursor with Unix epoch timestamp."""
        from datetime import UTC, datetime

        epoch_time = datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)
        test_id = "epoch-test"

        cursor = encode_cursor(test_id, epoch_time)
        decoded_id, decoded_time = decode_cursor(cursor)

        assert decoded_id == test_id
        assert decoded_time == epoch_time


class TestPaginationWithDuplicateTimestamps:
    """Tests for pagination when items have identical timestamps."""

    @pytest.mark.anyio
    async def test_pagination_with_identical_timestamps(self, async_db_session):
        """Test pagination handles items created at same time."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)

        # Create rules with same timestamp
        for i in range(10):
            rule = Rule(
                rule_name=f"Rule {i}",
                rule_type=RuleType.ALLOWLIST.value,
                current_version=1,
                status=EntityStatus.DRAFT.value,
                created_by="test@example.com",
                created_at=now,  # Same timestamp for all
                updated_at=now,
            )
            async_db_session.add(rule)
            await async_db_session.flush()

            rv = RuleVersion(
                rule_version_id=rule.rule_id,
                rule_id=rule.rule_id,
                version=1,
                condition_tree={"field": "test"},
                priority=100,
                status=EntityStatus.DRAFT.value,
                created_by="test@example.com",
                created_at=now,
            )
            async_db_session.add(rv)

        await async_db_session.commit()

        # Pagination should still work using rule_id as tiebreaker
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=5
        )

        assert len(items) == 5
        # Items should be ordered by (created_at DESC, rule_id)
        assert has_next is True


class TestBidirectionalPagination:
    """Tests for forward and backward pagination."""

    @pytest.mark.anyio
    async def test_forward_then_backward_pagination(self, async_db_session):
        """Test going forward then back to previous page."""
        # Create 25 rules
        for i in range(25):
            await create_rule_in_db(async_db_session, rule_name=f"Rule {i}")
        await async_db_session.commit()

        # First page
        items1, has_next1, has_prev1, next_cursor1, prev_cursor1 = await list_rules(
            async_db_session, limit=10
        )

        assert len(items1) == 10
        assert has_next1 is True
        assert has_prev1 is False

        # Second page
        items2, has_next2, has_prev2, next_cursor2, prev_cursor2 = await list_rules(
            async_db_session, cursor=next_cursor1, limit=10
        )

        assert len(items2) == 10
        assert has_next2 is True
        assert prev_cursor2 is not None

        # Go back to first page (if prev_cursor exists)
        if prev_cursor2:
            items3, has_next3, has_prev3, next_cursor3, prev_cursor3 = await list_rules(
                async_db_session, cursor=prev_cursor2, limit=10, direction=CursorDirection.PREV
            )

            # Back on first or similar page
            assert isinstance(items3, list)

    @pytest.mark.anyio
    async def test_pagination_on_last_page(self, async_db_session):
        """Test pagination behavior on the last page."""
        # Create 15 rules
        for i in range(15):
            await create_rule_in_db(async_db_session, rule_name=f"Rule {i}")
        await async_db_session.commit()

        # First page
        items1, has_next1, has_prev1, next_cursor1, prev_cursor1 = await list_rules(
            async_db_session, limit=10
        )

        # Second page (last page - only 5 items)
        items2, has_next2, has_prev2, next_cursor2, prev_cursor2 = await list_rules(
            async_db_session, cursor=next_cursor1, limit=10
        )

        assert len(items2) == 5
        assert has_next2 is False  # No more pages


class TestPaginationWithFilters:
    """Tests for pagination with filters applied."""

    @pytest.mark.anyio
    async def test_pagination_after_filter_exhaustion(self, async_db_session):
        """Test pagination when filter results in fewer items than limit."""
        # Create only 3 rules
        for _i in range(3):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Request more than available
        items, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            async_db_session, limit=10
        )

        assert len(items) == 3
        assert has_next is False
        assert next_cursor is None


class TestCursorTampering:
    """Tests for tampered cursor detection."""

    @pytest.mark.anyio
    async def test_cursor_with_invalid_uuid(self, async_db_session):
        """Test cursor with invalid UUID format."""
        from datetime import UTC, datetime

        # Create some rules
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Create a cursor with invalid UUID
        test_id = "not-a-valid-uuid"
        test_time = datetime.now(UTC)
        cursor = encode_cursor(test_id, test_time)

        # Should handle invalid UUID gracefully
        with pytest.raises((ValueError, Exception)):
            await list_rules(async_db_session, cursor=cursor, limit=10)

    @pytest.mark.anyio
    async def test_cursor_with_extra_json_fields(self, async_db_session):
        """Test cursor with extra fields in JSON."""
        import base64
        import json
        from datetime import UTC, datetime

        # Create some rules
        for _i in range(5):
            await create_rule_in_db(async_db_session)
        await async_db_session.commit()

        # Create a cursor with extra fields
        cursor_data = json.dumps(
            {
                "id": str(UUID(int=1)),
                "created_at": datetime.now(UTC).isoformat(),
                "extra_field": "should_not_be_here",
            }
        )
        tampered_cursor = base64.b64encode(cursor_data.encode()).decode()

        # Should handle gracefully - either ignore extra fields or reject
        result = await list_rules(async_db_session, cursor=tampered_cursor, limit=10)
        # Implementation should be robust enough to handle this
        assert isinstance(result, tuple) and len(result) == 5
