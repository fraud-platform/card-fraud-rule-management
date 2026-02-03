"""Unit tests for keyset/cursor-based pagination functionality."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.keyset_pagination import CursorDirection
from app.db.models import Approval, AuditLog, Rule, RuleSet
from app.repos.approval_repo import (
    list_approvals,
    list_audit_logs,
)
from app.repos.pagination import (
    build_keyset_query,
    decode_cursor,
    encode_cursor,
    get_keyset_page_info,
)
from app.repos.rule_repo import list_rules
from app.repos.ruleset_repo import list_rulesets


class TestCursorEncoding:
    """Test cursor encoding and decoding functions."""

    @pytest.mark.anyio
    async def test_encode_cursor(self):
        """Test cursor encoding produces valid base64."""
        id = "01234567-89ab-cdef-0123-456789abcdef"
        created_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=UTC)

        cursor = encode_cursor(id, created_at)

        # Should be base64 encoded
        assert isinstance(cursor, str)
        # Should be decodable
        decoded = json.loads(__import__("base64").b64decode(cursor.encode("utf-8")).decode("utf-8"))
        assert decoded["id"] == id
        assert decoded["created_at"] == created_at.isoformat()

    @pytest.mark.anyio
    async def test_decode_cursor(self):
        """Test cursor decoding retrieves original values."""
        id = "01234567-89ab-cdef-0123-456789abcdef"
        created_at = datetime(2024, 1, 15, 12, 30, 45, tzinfo=UTC)

        cursor = encode_cursor(id, created_at)
        decoded_id, decoded_created_at = decode_cursor(cursor)

        assert decoded_id == id
        assert decoded_created_at == created_at

    @pytest.mark.anyio
    async def test_decode_invalid_cursor(self):
        """Test decoding invalid cursor raises ValueError."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("invalid-base64!!!")

    @pytest.mark.anyio
    async def test_decode_malformed_json_cursor(self):
        """Test decoding cursor with invalid JSON raises ValueError."""
        import base64

        malformed = base64.b64encode(b"not valid json").decode("utf-8")
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(malformed)

    @pytest.mark.anyio
    async def test_decode_missing_fields_cursor(self):
        """Test decoding cursor with missing fields raises ValueError."""
        import base64

        incomplete = json.dumps({"id": "test-id"})  # Missing created_at
        malformed = base64.b64encode(incomplete.encode("utf-8")).decode("utf-8")
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(malformed)


class TestKeysetPagination:
    """Test keyset pagination queries and page info calculation."""

    @pytest.mark.anyio
    async def test_build_query_first_page(self):
        """Test building query for first page (no cursor)."""
        stmt = build_keyset_query(
            Rule,
            cursor=None,
            direction=CursorDirection.NEXT,
            limit=50,
            order_column="created_at",
            id_column="rule_id",
        )

        # Should have ordering but no cursor filter
        assert "WHERE" not in str(stmt)
        assert "ORDER BY" in str(stmt)
        assert "LIMIT" in str(stmt)

    @pytest.mark.anyio
    async def test_build_query_next_page(self):
        """Test building query for next page with cursor."""
        cursor_id = "01234567-89ab-cdef-0123-456789abcdef"
        cursor_created_at = datetime(2024, 1, 15, tzinfo=UTC)

        stmt = build_keyset_query(
            Rule,
            cursor=(cursor_id, cursor_created_at),
            direction=CursorDirection.NEXT,
            limit=50,
            order_column="created_at",
            id_column="rule_id",
        )

        # Should have cursor filter
        assert "WHERE" in str(stmt)
        # Should order by created_at DESC, rule_id DESC
        assert "ORDER BY" in str(stmt)

    @pytest.mark.anyio
    async def test_build_query_prev_page(self):
        """Test building query for previous page with cursor."""
        cursor_id = "01234567-89ab-cdef-0123-456789abcdef"
        cursor_created_at = datetime(2024, 1, 15, tzinfo=UTC)

        stmt = build_keyset_query(
            Rule,
            cursor=(cursor_id, cursor_created_at),
            direction=CursorDirection.PREV,
            limit=50,
            order_column="created_at",
            id_column="rule_id",
        )

        # Should have cursor filter
        assert "WHERE" in str(stmt)
        assert "ORDER BY" in str(stmt)

    @pytest.mark.anyio
    async def test_get_page_info_empty_list(self):
        """Test page info calculation with empty list."""
        trimmed_items, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
            [], limit=50, direction=CursorDirection.NEXT
        )

        assert trimmed_items == []
        assert has_next is False
        assert has_prev is False
        assert next_cursor is None
        assert prev_cursor is None

    @pytest.mark.anyio
    async def test_get_page_info_full_page_next_direction(self):
        """Test page info with full page going forward."""
        # Create mock items with required attributes
        items = [
            Mock(
                rule_id=f"id-{i}",
                created_at=datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
            )
            for i in range(50)
        ]
        # Add one extra item to indicate more pages
        items.append(
            Mock(
                rule_id="id-extra",
                created_at=datetime(2024, 1, 14, 12, 0, 0, tzinfo=UTC),
            )
        )

        trimmed_items, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
            items, limit=50, direction=CursorDirection.NEXT, is_first_page=True
        )

        assert len(trimmed_items) == 50  # Extra item should be trimmed
        assert has_next is True
        assert has_prev is False  # First page, so has_prev is False
        assert next_cursor is not None
        assert prev_cursor is None  # First page, so prev_cursor is None

    @pytest.mark.anyio
    async def test_get_page_info_last_page_next_direction(self):
        """Test page info with last page going forward."""
        items = [
            Mock(
                rule_id=f"id-{i}",
                created_at=datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
            )
            for i in range(30)
        ]

        trimmed_items, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
            items, limit=50, direction=CursorDirection.NEXT, is_first_page=True
        )

        assert len(trimmed_items) == 30
        assert has_next is False
        assert has_prev is False  # First page, so has_prev is False
        assert next_cursor is None
        assert prev_cursor is None  # First page, so prev_cursor is None


class TestRuleKeysetPagination:
    """Integration tests for Rule keyset pagination."""

    @pytest.mark.anyio
    async def test_list_rules_first_page(self, clean_async_db_session: AsyncSession):
        """Test getting first page of rules with keyset pagination."""
        # Create test rules
        now = datetime.now(UTC)
        for i in range(10):
            rule = Rule(
                rule_name=f"Test Rule {i}",
                description=f"Description {i}",
                rule_type="ALLOWLIST",
                current_version=1,
                status="DRAFT",
                version=1,
                created_by="test-user",
                created_at=now - timedelta(hours=i),
            )
            clean_async_db_session.add(rule)
        await clean_async_db_session.commit()

        # Get first page
        rules, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        assert len(rules) == 5
        assert has_next is True
        assert has_prev is False  # First page
        assert next_cursor is not None
        assert prev_cursor is None  # First page

        # Verify ordering (most recent first)
        for i in range(4):
            assert rules[i].created_at >= rules[i + 1].created_at

    @pytest.mark.anyio
    async def test_list_rules_next_page(self, clean_async_db_session: AsyncSession):
        """Test getting next page of rules with cursor."""
        # Create test rules
        now = datetime.now(UTC)
        for i in range(15):
            rule = Rule(
                rule_name=f"Test Rule {i}",
                description=f"Description {i}",
                rule_type="ALLOWLIST",
                current_version=1,
                status="DRAFT",
                version=1,
                created_by="test-user",
                created_at=now - timedelta(hours=i),
            )
            clean_async_db_session.add(rule)
        await clean_async_db_session.commit()

        # Get first page
        rules1, _, _, next_cursor, _ = await list_rules(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        # Get second page
        rules2, has_next, has_prev, next_cursor2, prev_cursor2 = await list_rules(
            clean_async_db_session, cursor=next_cursor, limit=5, direction=CursorDirection.NEXT
        )

        assert len(rules2) == 5
        assert has_next is True
        assert has_prev is True
        assert next_cursor2 is not None
        assert prev_cursor2 is not None

        # Verify no duplicates between pages
        ids1 = {r.rule_id for r in rules1}
        ids2 = {r.rule_id for r in rules2}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.anyio
    async def test_list_rules_prev_page(self, clean_async_db_session: AsyncSession):
        """Test getting previous page of rules with cursor."""
        # Create test rules
        now = datetime.now(UTC)
        for i in range(15):
            rule = Rule(
                rule_name=f"Test Rule {i}",
                description=f"Description {i}",
                rule_type="ALLOWLIST",
                current_version=1,
                status="DRAFT",
                version=1,
                created_by="test-user",
                created_at=now - timedelta(hours=i),
            )
            clean_async_db_session.add(rule)
        await clean_async_db_session.commit()

        # Get first page to get a cursor
        rules1, _, _, next_cursor, _ = await list_rules(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        # Get second page
        rules2, _, _, next_cursor2, prev_cursor2 = await list_rules(
            clean_async_db_session, cursor=next_cursor, limit=5, direction=CursorDirection.NEXT
        )

        # Go back to first page using prev_cursor
        rules_back, has_next, has_prev, next_cursor_back, prev_cursor_back = await list_rules(
            clean_async_db_session, cursor=prev_cursor2, limit=5, direction=CursorDirection.PREV
        )

        assert len(rules_back) == 5
        assert has_next is True
        assert has_prev is False  # Back to first page

        # Verify we got the same items
        ids1 = {r.rule_id for r in rules1}
        ids_back = {r.rule_id for r in rules_back}
        assert ids1 == ids_back


class TestRuleSetKeysetPagination:
    """Integration tests for RuleSet keyset pagination."""

    @pytest.mark.anyio
    async def test_list_rulesets_first_page(self, clean_async_db_session: AsyncSession):
        """Test getting first page of rulesets with keyset pagination."""
        # Create test rulesets with different combinations to avoid unique constraint
        # Unique constraint is on (environment, region, country, rule_type)
        now = datetime.now(UTC)
        regions = ["AMERICAS", "EMEA", "APAC", "INDIA"]
        countries = ["US", "UK", "SG", "IN"]
        rule_types = ["ALLOWLIST", "BLOCKLIST", "AUTH", "MONITORING"]
        environments = [
            "test1",
            "test2",
            "test3",
            "test4",
            "test5",
            "test6",
            "test7",
            "test8",
            "test9",
            "test10",
        ]

        for i in range(10):
            # Use unique environment to avoid unique constraint violation
            environment = environments[i]
            region = regions[i % len(regions)]
            country = countries[i % len(countries)]
            rule_type = rule_types[i % len(rule_types)]
            ruleset = RuleSet(
                environment=environment,
                region=region,
                country=country,
                rule_type=rule_type,
                name=f"Test RuleSet {i}",
                description=f"Description {i}",
                created_by="test-user",
                created_at=now - timedelta(hours=i),
            )
            clean_async_db_session.add(ruleset)
        await clean_async_db_session.commit()

        # Get first page
        rulesets, has_next, has_prev, next_cursor, prev_cursor = await list_rulesets(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        assert len(rulesets) == 5
        assert has_next is True
        assert has_prev is False
        assert next_cursor is not None
        assert prev_cursor is None


class TestApprovalKeysetPagination:
    """Integration tests for Approval keyset pagination."""

    @pytest.mark.anyio
    async def test_list_approvals(self, clean_async_db_session: AsyncSession):
        """Test approvals with keyset pagination."""
        # Create test approvals
        now = datetime.now(UTC)
        for i in range(10):
            approval = Approval(
                entity_type="RULE_VERSION",
                entity_id=f"01234567-89ab-cdef-{i:04d}-456789abcdef",
                action="SUBMIT",
                maker="test-user",
                status="PENDING",
                created_at=now - timedelta(hours=i),
            )
            clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # Get first page
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        assert len(approvals) == 5
        assert has_next is True
        assert has_prev is False
        assert next_cursor is not None
        assert prev_cursor is None

        # Verify all approvals are dicts
        for approval in approvals:
            assert isinstance(approval, dict)
            assert "approval_id" in approval
            assert "created_at" in approval


class TestAuditLogKeysetPagination:
    """Integration tests for AuditLog keyset pagination."""

    @pytest.mark.anyio
    async def test_list_audit_logs(self, clean_async_db_session: AsyncSession):
        """Test audit logs with keyset pagination."""
        # Create test audit logs
        now = datetime.now(UTC)
        for i in range(10):
            log = AuditLog(
                entity_type="RULE",
                entity_id=f"01234567-89ab-cdef-{i:04d}-456789abcdef",
                action="CREATE",
                old_value=None,
                new_value={"test": "data"},
                performed_by="test-user",
                performed_at=now - timedelta(hours=i),
            )
            clean_async_db_session.add(log)
        await clean_async_db_session.commit()

        # Get first page
        logs, has_next, has_prev, next_cursor, prev_cursor = await list_audit_logs(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        assert len(logs) == 5
        assert has_next is True
        assert has_prev is False
        assert next_cursor is not None
        assert prev_cursor is None


class TestBoundaryConditions:
    """Test edge cases and boundary conditions."""

    @pytest.mark.anyio
    async def test_empty_result_set(self, clean_async_db_session: AsyncSession):
        """Test pagination with empty result set."""
        rules, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            clean_async_db_session, limit=10, direction=CursorDirection.NEXT
        )

        assert len(rules) == 0
        assert has_next is False
        assert has_prev is False
        assert next_cursor is None
        assert prev_cursor is None

    @pytest.mark.anyio
    async def test_single_item(self, clean_async_db_session: AsyncSession):
        """Test pagination with single item."""
        rule = Rule(
            rule_name="Single Rule",
            description="Test",
            rule_type="ALLOWLIST",
            current_version=1,
            status="DRAFT",
            version=1,
            created_by="test-user",
        )
        clean_async_db_session.add(rule)
        await clean_async_db_session.commit()

        rules, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
            clean_async_db_session, limit=10, direction=CursorDirection.NEXT
        )

        assert len(rules) == 1
        assert has_next is False
        assert has_prev is False
        assert next_cursor is None
        assert prev_cursor is None

    @pytest.mark.anyio
    async def test_duplicate_timestamps(self, clean_async_db_session: AsyncSession):
        """Test pagination handles items with same timestamp correctly."""
        # Create rules with same timestamp but different IDs
        now = datetime.now(UTC)
        for i in range(10):
            rule = Rule(
                rule_name=f"Test Rule {i}",
                description=f"Description {i}",
                rule_type="ALLOWLIST",
                current_version=1,
                status="DRAFT",
                version=1,
                created_by="test-user",
                created_at=now,  # All same timestamp
            )
            clean_async_db_session.add(rule)
        await clean_async_db_session.commit()

        # Get first page
        rules1, _, _, next_cursor, _ = await list_rules(
            clean_async_db_session, limit=5, direction=CursorDirection.NEXT
        )

        # Get second page
        rules2, _, _, _, _ = await list_rules(
            clean_async_db_session, cursor=next_cursor, limit=5, direction=CursorDirection.NEXT
        )

        # Verify no duplicates despite same timestamps
        ids1 = {r.rule_id for r in rules1}
        ids2 = {r.rule_id for r in rules2}
        assert ids1.isdisjoint(ids2)
        assert len(ids1) + len(ids2) == 10

    @pytest.mark.anyio
    async def test_invalid_cursor_error_handling(self, clean_async_db_session: AsyncSession):
        """Test that invalid cursor is handled gracefully."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            await list_rules(
                clean_async_db_session,
                cursor="invalid-cursor",
                limit=10,
                direction=CursorDirection.NEXT,
            )


# Note: Uses clean_async_db_session fixture from conftest.py (PostgreSQL, not SQLite)
