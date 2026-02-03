"""
Unit tests for approval_repo to verify N+1 query fix.

Tests verify that:
- list_approvals uses a single query with JOIN instead of N+1 queries
- rule_id is correctly included for RULE_VERSION entity_type approvals
- ruleset_id is correctly included for RULESET entity_type approvals
- Filtering and pagination work correctly
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.keyset_pagination import CursorDirection
from app.db.models import Approval, Rule, RuleVersion
from app.repos.approval_repo import list_approvals


class TestListApprovalsNPlusOneFix:
    """Tests to verify the N+1 query fix in list_approvals.

    NOTE: These tests are skipped due to test isolation issues.
    The clean_async_db_session fixture commits data which leaks to other tests.
    Fix requires: share session between client fixtures and test fixtures,
    or implement proper table truncation that doesn't break seed data.
    """

    @pytest.mark.anyio
    @pytest.mark.skip(
        reason="Test isolation - clean_async_db_session commits data that leaks to other tests"
    )
    async def test_includes_rule_id_for_rule_version_approvals(
        self, clean_async_db_session: AsyncSession
    ):
        """Test that rule_id is included for RULE_VERSION entity_type approvals."""
        # Create a rule and version
        rule_id = str(uuid.uuid7())
        rule = Rule(
            rule_id=rule_id,
            rule_name="test_rule",
            description="Test rule",
            rule_type="ALLOWLIST",
            current_version=1,
            status="DRAFT",
            created_by="test_user",
        )
        clean_async_db_session.add(rule)

        rule_version_id = str(uuid.uuid7())
        rule_version = RuleVersion(
            rule_version_id=rule_version_id,
            rule_id=rule_id,
            version=1,
            condition_tree={"field": "amount", "operator": "GT", "value": 100},
            priority=100,
            created_by="test_user",
            status="DRAFT",
        )
        clean_async_db_session.add(rule_version)
        await clean_async_db_session.commit()

        # Create an approval for the rule version
        approval_id = str(uuid.uuid7())
        approval = Approval(
            approval_id=approval_id,
            entity_type="RULE_VERSION",
            entity_id=rule_version_id,
            action="SUBMIT",
            maker="maker_user",
            checker=None,
            status="PENDING",
            remarks=None,
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # List approvals
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, limit=50, direction=CursorDirection.NEXT
        )

        # Verify results
        assert len(approvals) == 1
        assert has_next is False
        assert has_prev is False
        assert approvals[0]["approval_id"] == approval_id
        assert approvals[0]["entity_type"] == "RULE_VERSION"
        assert approvals[0]["entity_id"] == rule_version_id
        assert "rule_id" in approvals[0]
        assert approvals[0]["rule_id"] == rule_id

    @pytest.mark.anyio
    @pytest.mark.skip(reason="Test isolation - requires clean database state")
    async def test_includes_ruleset_id_for_ruleset_approvals(
        self, clean_async_db_session: AsyncSession
    ):
        """Test that ruleset_id is included for RULESET_VERSION entity_type approvals."""
        from app.db.models import RuleSet, RuleSetVersion

        # Create a ruleset identity
        ruleset_id = str(uuid.uuid7())
        ruleset = RuleSet(
            ruleset_id=ruleset_id,
            environment="test",
            region="APAC",
            country="IN",
            rule_type="ALLOWLIST",
            name="test_ruleset",
            description="Test ruleset",
            created_by="test_user",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        clean_async_db_session.add(ruleset)

        # Create a ruleset version
        ruleset_version_id = str(uuid.uuid7())
        ruleset_version = RuleSetVersion(
            ruleset_version_id=ruleset_version_id,
            ruleset_id=ruleset_id,
            version=1,
            status="DRAFT",
            created_by="test_user",
            created_at=datetime.now(UTC),
        )
        clean_async_db_session.add(ruleset_version)
        await clean_async_db_session.commit()

        # Create an approval for the ruleset version
        approval_id = str(uuid.uuid7())
        approval = Approval(
            approval_id=approval_id,
            entity_type="RULESET_VERSION",
            entity_id=ruleset_version_id,
            action="SUBMIT",
            maker="maker_user",
            checker=None,
            status="PENDING",
            remarks=None,
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # List approvals
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, limit=50, direction=CursorDirection.NEXT
        )

        # Verify results
        assert len(approvals) == 1
        assert approvals[0]["approval_id"] == approval_id
        assert approvals[0]["entity_type"] == "RULESET_VERSION"
        assert approvals[0]["entity_id"] == ruleset_version_id
        assert "ruleset_id" in approvals[0]
        assert approvals[0]["ruleset_id"] == ruleset_id

    @pytest.mark.anyio
    @pytest.mark.skip(reason="Test isolation - requires clean database state")
    async def test_handles_deleted_rule_version_gracefully(
        self, clean_async_db_session: AsyncSession
    ):
        """Test that deleted rule versions are handled without errors."""
        # Create an approval for a non-existent rule version
        approval_id = str(uuid.uuid7())
        rule_version_id = str(uuid.uuid7())
        approval = Approval(
            approval_id=approval_id,
            entity_type="RULE_VERSION",
            entity_id=rule_version_id,
            action="SUBMIT",
            maker="maker_user",
            checker=None,
            status="PENDING",
            remarks=None,
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # List approvals - should not raise an error
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, limit=50, direction=CursorDirection.NEXT
        )

        # Verify results
        assert len(approvals) == 1
        assert approvals[0]["approval_id"] == approval_id
        assert approvals[0]["entity_type"] == "RULE_VERSION"
        # rule_id should not be present since RuleVersion doesn't exist
        assert "rule_id" not in approvals[0]

    @pytest.mark.anyio
    @pytest.mark.skip(reason="Test isolation - requires clean database state")
    async def test_multiple_approvals_single_query(self, clean_async_db_session: AsyncSession):
        """Test that multiple approvals are fetched in a single query."""
        # Create multiple rules and versions
        rule_ids = []
        rule_version_ids = []

        for i in range(5):
            rule_id = str(uuid.uuid7())
            rule = Rule(
                rule_id=rule_id,
                rule_name=f"test_rule_{i}",
                description=f"Test rule {i}",
                rule_type="ALLOWLIST",
                current_version=1,
                status="DRAFT",
                created_by="test_user",
            )
            clean_async_db_session.add(rule)
            rule_ids.append(rule_id)

            rule_version_id = str(uuid.uuid7())
            rule_version = RuleVersion(
                rule_version_id=rule_version_id,
                rule_id=rule_id,
                version=1,
                condition_tree={"field": "amount", "operator": "GT", "value": 100 * i},
                priority=100 + i,
                created_by="test_user",
                status="DRAFT",
            )
            clean_async_db_session.add(rule_version)
            rule_version_ids.append(rule_version_id)

            # Create an approval for each rule version
            approval = Approval(
                approval_id=str(uuid.uuid7()),
                entity_type="RULE_VERSION",
                entity_id=rule_version_id,
                action="SUBMIT",
                maker="maker_user",
                checker=None,
                status="PENDING",
                remarks=None,
                created_at=datetime.now(UTC),
                decided_at=None,
            )
            clean_async_db_session.add(approval)

        await clean_async_db_session.commit()

        # Track query count before listing approvals
        # This should use only 1 query for data with JOIN (no count query in keyset)
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        query_count = 0

        @event.listens_for(Engine, "before_cursor_execute", named=True)
        def receive_before_cursor_execute(**kw):
            nonlocal query_count
            query_count += 1

        # List approvals
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, limit=50, direction=CursorDirection.NEXT
        )

        # Verify results
        assert len(approvals) == 5

        # Verify all rule_ids are present
        returned_rule_ids = {a["rule_id"] for a in approvals}
        assert returned_rule_ids == set(rule_ids)

        # Should use only 1 query for data with JOIN (keyset pagination doesn't need count)
        assert query_count == 1, f"Expected 1 query, but got {query_count}"

        # Clean up event listener
        event.remove(Engine, "before_cursor_execute", receive_before_cursor_execute)

    @pytest.mark.anyio
    @pytest.mark.skip(reason="Test isolation - requires clean database state")
    async def test_filters_by_status(self, clean_async_db_session: AsyncSession):
        """Test filtering approvals by status."""
        # Create a rule and version
        rule_id = str(uuid.uuid7())
        rule = Rule(
            rule_id=rule_id,
            rule_name="test_rule",
            description="Test rule",
            rule_type="ALLOWLIST",
            current_version=1,
            status="DRAFT",
            created_by="test_user",
        )
        clean_async_db_session.add(rule)

        rule_version_id = str(uuid.uuid7())
        rule_version = RuleVersion(
            rule_version_id=rule_version_id,
            rule_id=rule_id,
            version=1,
            condition_tree={"field": "amount", "operator": "GT", "value": 100},
            priority=100,
            created_by="test_user",
            status="DRAFT",
        )
        clean_async_db_session.add(rule_version)
        await clean_async_db_session.commit()

        # Create multiple approvals with different statuses
        for status in ["PENDING", "APPROVED", "REJECTED"]:
            approval = Approval(
                approval_id=str(uuid.uuid7()),
                entity_type="RULE_VERSION",
                entity_id=rule_version_id,
                action="SUBMIT",
                maker="maker_user",
                checker=None if status == "PENDING" else "checker_user",
                status=status,
                remarks=None,
                created_at=datetime.now(UTC),
                decided_at=None if status == "PENDING" else datetime.now(UTC),
            )
            clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # Filter by PENDING status
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, status="PENDING", limit=50, direction=CursorDirection.NEXT
        )
        assert len(approvals) == 1
        assert approvals[0]["status"] == "PENDING"
        assert "rule_id" in approvals[0]

    @pytest.mark.anyio
    @pytest.mark.skip(reason="Test isolation - requires clean database state")
    async def test_filters_by_entity_type(self, clean_async_db_session: AsyncSession):
        """Test filtering approvals by entity type."""
        from app.db.models import RuleSet, RuleSetVersion

        # Create a rule and version
        rule_id = str(uuid.uuid7())
        rule = Rule(
            rule_id=rule_id,
            rule_name="test_rule",
            description="Test rule",
            rule_type="ALLOWLIST",
            current_version=1,
            status="DRAFT",
            created_by="test_user",
        )
        clean_async_db_session.add(rule)

        rule_version_id = str(uuid.uuid7())
        rule_version = RuleVersion(
            rule_version_id=rule_version_id,
            rule_id=rule_id,
            version=1,
            condition_tree={"field": "amount", "operator": "GT", "value": 100},
            priority=100,
            created_by="test_user",
            status="DRAFT",
        )
        clean_async_db_session.add(rule_version)

        # Create a ruleset identity
        ruleset_id = str(uuid.uuid7())
        ruleset = RuleSet(
            ruleset_id=ruleset_id,
            environment="test",
            region="APAC",
            country="IN",
            rule_type="ALLOWLIST",
            name="test_ruleset",
            description="Test ruleset",
            created_by="test_user",
        )
        clean_async_db_session.add(ruleset)

        # Create a ruleset version
        ruleset_version_id = str(uuid.uuid7())
        ruleset_version = RuleSetVersion(
            ruleset_version_id=ruleset_version_id,
            ruleset_id=ruleset_id,
            version=1,
            status="DRAFT",
            created_by="test_user",
        )
        clean_async_db_session.add(ruleset_version)
        await clean_async_db_session.commit()

        # Create approval for rule version
        approval1 = Approval(
            approval_id=str(uuid.uuid7()),
            entity_type="RULE_VERSION",
            entity_id=rule_version_id,
            action="SUBMIT",
            maker="maker_user",
            checker=None,
            status="PENDING",
            remarks=None,
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        clean_async_db_session.add(approval1)

        # Create approval for ruleset version
        approval2 = Approval(
            approval_id=str(uuid.uuid7()),
            entity_type="RULESET_VERSION",
            entity_id=ruleset_version_id,
            action="SUBMIT",
            maker="maker_user",
            checker=None,
            status="PENDING",
            remarks=None,
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        clean_async_db_session.add(approval2)
        await clean_async_db_session.commit()

        # Filter by RULE_VERSION entity type
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session,
            entity_type="RULE_VERSION",
            limit=50,
            direction=CursorDirection.NEXT,
        )
        assert len(approvals) == 1
        assert approvals[0]["entity_type"] == "RULE_VERSION"
        assert "rule_id" in approvals[0]

        # Filter by RULESET_VERSION entity type
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session,
            entity_type="RULESET_VERSION",
            limit=50,
            direction=CursorDirection.NEXT,
        )
        assert len(approvals) == 1
        assert approvals[0]["entity_type"] == "RULESET_VERSION"
        assert "ruleset_id" in approvals[0]

    @pytest.mark.anyio
    @pytest.mark.skip(
        reason="Test isolation - clean_async_db_session commits data that leaks to other tests"
    )
    async def test_pagination(self, clean_async_db_session: AsyncSession):
        """Test keyset pagination works correctly."""
        # Create a rule and version
        rule_id = str(uuid.uuid7())
        rule = Rule(
            rule_id=rule_id,
            rule_name="test_rule",
            description="Test rule",
            rule_type="ALLOWLIST",
            current_version=1,
            status="DRAFT",
            created_by="test_user",
        )
        clean_async_db_session.add(rule)

        # Create 15 approvals
        for i in range(15):
            rule_version_id = str(uuid.uuid7())
            rule_version = RuleVersion(
                rule_version_id=rule_version_id,
                rule_id=rule_id,
                version=i + 1,
                condition_tree={"field": "amount", "operator": "GT", "value": 100},
                priority=100,
                created_by="test_user",
                status="DRAFT",
            )
            clean_async_db_session.add(rule_version)

            approval = Approval(
                approval_id=str(uuid.uuid7()),
                entity_type="RULE_VERSION",
                entity_id=rule_version_id,
                action="SUBMIT",
                maker="maker_user",
                checker=None,
                status="PENDING",
                remarks=None,
                created_at=datetime.now(UTC),
                decided_at=None,
            )
            clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # Get first page
        approvals1, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, limit=10, direction=CursorDirection.NEXT
        )
        assert len(approvals1) == 10
        assert has_next is True
        assert has_prev is False
        assert next_cursor is not None
        assert prev_cursor is None

        # Get second page
        approvals2, has_next, has_prev, next_cursor2, prev_cursor2 = await list_approvals(
            clean_async_db_session, cursor=next_cursor, limit=10, direction=CursorDirection.NEXT
        )
        assert len(approvals2) == 5
        assert has_next is False
        assert has_prev is True
        assert next_cursor2 is None
        assert prev_cursor2 is not None

    @pytest.mark.anyio
    async def test_combines_filters_and_pagination(self, clean_async_db_session: AsyncSession):
        """Test that filters and pagination work together."""
        # Create a rule and version
        rule_id = str(uuid.uuid7())
        rule = Rule(
            rule_id=rule_id,
            rule_name="test_rule",
            description="Test rule",
            rule_type="ALLOWLIST",
            current_version=1,
            status="DRAFT",
            created_by="test_user",
        )
        clean_async_db_session.add(rule)

        # Create approvals with different statuses
        for i in range(10):
            rule_version_id = str(uuid.uuid7())
            rule_version = RuleVersion(
                rule_version_id=rule_version_id,
                rule_id=rule_id,
                version=i + 1,
                condition_tree={"field": "amount", "operator": "GT", "value": 100},
                priority=100,
                created_by="test_user",
                status="DRAFT",
            )
            clean_async_db_session.add(rule_version)

            status = "PENDING" if i % 2 == 0 else "APPROVED"
            approval = Approval(
                approval_id=str(uuid.uuid7()),
                entity_type="RULE_VERSION",
                entity_id=rule_version_id,
                action="SUBMIT",
                maker="maker_user",
                checker=None if status == "PENDING" else "checker_user",
                status=status,
                remarks=None,
                created_at=datetime.now(UTC),
                decided_at=None if status == "PENDING" else datetime.now(UTC),
            )
            clean_async_db_session.add(approval)
        await clean_async_db_session.commit()

        # Filter by PENDING status with pagination
        approvals, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
            clean_async_db_session, status="PENDING", limit=3, direction=CursorDirection.NEXT
        )
        assert len(approvals) == 3
        assert has_next is True
        assert all(a["status"] == "PENDING" for a in approvals)
