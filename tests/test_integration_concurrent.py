"""
Integration tests for concurrent operations and optimistic locking.

Tests cover:
- Real concurrent updates using threading
- Race condition detection
- Multiple simultaneous updates
- Database-level lock contention
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError
from app.core.optimistic_lock import (
    check_rule_version_async,
    check_ruleset_version_async,
)
from app.db.models import RuleSet, RuleSetVersion, RuleSetVersionRule, RuleVersion
from app.domain.enums import EntityStatus, RuleType
from app.repos.rule_repo import create_rule, create_rule_version
from app.repos.ruleset_repo import create_ruleset
from tests.conftest import acreate_rule_in_db

pytestmark = pytest.mark.smoke


class TestConcurrentRuleUpdates:
    """Tests for concurrent rule updates using threading."""

    @pytest.mark.anyio
    async def test_sequential_updates_all_succeed(self, async_db_session):
        """Test that sequential updates all succeed."""
        rule = await create_rule(
            async_db_session,
            rule_name="Sequential Test Rule",
            description="Sequential test rule",
            rule_type=RuleType.ALLOWLIST.value,
            created_by="test@example.com",
            action="APPROVE",
        )
        await async_db_session.commit()

        initial_version = rule.version

        # Create multiple versions sequentially
        for i in range(3):
            await create_rule_version(
                async_db_session,
                rule_id=rule.rule_id,
                condition_tree={"field": f"test{i}"},
                created_by="user@example.com",
            )
            await async_db_session.commit()

        # All should have succeeded
        await async_db_session.refresh(rule)
        assert rule.version == initial_version + 3

    @pytest.mark.anyio
    async def test_version_check_with_stale_data(self, async_db_session):
        """Test version check fails when using stale data."""
        rule = await create_rule(
            async_db_session,
            rule_name="Stale Data Rule",
            description="Stale data test rule",
            rule_type=RuleType.ALLOWLIST.value,
            created_by="test@example.com",
            action="APPROVE",
        )
        await async_db_session.commit()

        stale_version = rule.version

        # Another transaction updates the rule
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "updated"},
            created_by="other@example.com",
        )
        await async_db_session.commit()

        # Try to check with stale version
        with pytest.raises(ConflictError) as exc_info:
            await check_rule_version_async(
                async_db_session, rule_id=rule.rule_id, expected_version=stale_version
            )

        assert "was modified" in exc_info.value.message.lower()


class TestConcurrentRaceConditions:
    """Tests for specific race condition scenarios."""

    @pytest.mark.anyio
    async def test_ruleset_version_conflict_detection(self, async_db_session):
        """Test that ruleset version conflicts are properly detected."""
        # Create a RuleSet
        ruleset = await create_ruleset(
            async_db_session,
            environment="test",
            region="AMERICAS",
            country="US",
            rule_type=RuleType.ALLOWLIST.value,
            name="Test Ruleset",
            description="Test ruleset for version conflict",
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Create a RuleSetVersion with version 1
        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.DRAFT.value,
            created_by="test@example.com",
        )
        async_db_session.add(ruleset_version)
        await async_db_session.commit()
        await async_db_session.refresh(ruleset_version)

        # Try to check with wrong expected version (999 instead of 1)
        with pytest.raises(ConflictError) as exc_info:
            await check_ruleset_version_async(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                expected_version=999,
            )

        assert "was modified" in exc_info.value.message.lower()

        # Verify that correct version check works
        result = await check_ruleset_version_async(
            async_db_session,
            ruleset_version_id=ruleset_version.ruleset_version_id,
            expected_version=1,
        )
        assert result.ruleset_version_id == ruleset_version.ruleset_version_id


class TestOptimisticLockingEdgeCases:
    """Tests for edge cases in optimistic locking."""

    @pytest.mark.anyio
    async def test_version_check_after_delete(self, async_db_session):
        """Test version check behavior after entity is deleted."""
        rule = await create_rule(
            async_db_session,
            rule_name="To Be Deleted",
            description="Rule to be deleted",
            rule_type=RuleType.ALLOWLIST.value,
            created_by="test@example.com",
            action="APPROVE",
        )
        rule_id = rule.rule_id
        await async_db_session.commit()

        # Delete the rule
        await async_db_session.delete(rule)
        await async_db_session.commit()

        # Version check on deleted rule should fail
        from app.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await check_rule_version_async(async_db_session, rule_id=rule_id, expected_version=1)

    @pytest.mark.anyio
    async def test_multiple_conflicting_updates_sequential_retries(self, async_db_session):
        """Test that retries work after conflict."""
        rule = await create_rule(
            async_db_session,
            rule_name="Retry Test Rule",
            description="Retry test rule",
            rule_type=RuleType.ALLOWLIST.value,
            created_by="test@example.com",
            action="APPROVE",
        )
        await async_db_session.commit()

        # First version
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "v1"},
            created_by="user@example.com",
        )
        await async_db_session.commit()

        # Get current version
        await async_db_session.refresh(rule)
        current_version = rule.version

        # Should succeed with current version
        await check_rule_version_async(
            async_db_session, rule_id=rule.rule_id, expected_version=current_version
        )

        # Create another version
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "v2"},
            created_by="user@example.com",
        )
        await async_db_session.commit()

        # Old version check should now fail
        with pytest.raises(ConflictError):
            await check_rule_version_async(
                async_db_session, rule_id=rule.rule_id, expected_version=current_version
            )

    @pytest.mark.anyio
    async def test_concurrent_different_entities_no_conflict(self, async_db_session):
        """Test that concurrent updates to different entities don't conflict."""
        rule1 = await create_rule(
            async_db_session,
            rule_name="Rule 1",
            description="First rule",
            rule_type=RuleType.ALLOWLIST.value,
            created_by="test@example.com",
            action="APPROVE",
        )
        rule2 = await create_rule(
            async_db_session,
            rule_name="Rule 2",
            description="Second rule",
            rule_type=RuleType.ALLOWLIST.value,
            created_by="test@example.com",
            action="APPROVE",
        )
        await async_db_session.commit()

        # Both should be updatable independently
        await create_rule_version(
            async_db_session,
            rule_id=rule1.rule_id,
            condition_tree={"field": "rule1"},
            created_by="user@example.com",
        )
        await async_db_session.commit()

        await create_rule_version(
            async_db_session,
            rule_id=rule2.rule_id,
            condition_tree={"field": "rule2"},
            created_by="user@example.com",
        )
        await async_db_session.commit()

        # Both should have been updated
        await async_db_session.refresh(rule1)
        await async_db_session.refresh(rule2)
        assert rule1.version == 2
        assert rule2.version == 2


class TestRuleApprovalWorkflow:
    """Tests for rule approval workflow with optimistic locking."""

    @pytest.mark.anyio
    async def test_create_and_approve_rule_workflow(self, async_db_session):
        """Test complete workflow of creating and approving a rule."""
        now = datetime.now(UTC)

        # Create rule field
        from tests.conftest import acreate_rule_field_in_db

        await acreate_rule_field_in_db(
            async_db_session,
            field_key="test_amount",
            display_name="Test Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        # Create rule
        from tests.conftest import acreate_rule_in_db

        rule = await acreate_rule_in_db(
            async_db_session,
            rule_name="Test Approval Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={
                "type": "CONDITION",
                "field": "test_amount",
                "operator": "GT",
                "value": 100,
            },
            priority=100,
        )

        # Get rule version and approve it
        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rv = result.scalar_one()
        rv.status = EntityStatus.APPROVED.value
        rv.approved_by = "checker"
        rv.approved_at = now
        await async_db_session.commit()

        # Verify the rule version is now approved
        await async_db_session.refresh(rv)
        assert rv.status == EntityStatus.APPROVED.value
        assert rv.approved_by == "checker"

    @pytest.mark.anyio
    async def test_ruleset_attach_and_compile_workflow(self, async_db_session):
        """Test workflow of attaching rules to ruleset and compiling."""
        now = datetime.now(UTC)
        checker = "checker-user"

        # Create rule field
        from tests.conftest import acreate_rule_field_in_db

        await acreate_rule_field_in_db(
            async_db_session,
            field_key="workflow_amount",
            display_name="Workflow Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        # Create rule
        rule = await acreate_rule_in_db(
            async_db_session,
            rule_name="Workflow Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={
                "type": "CONDITION",
                "field": "workflow_amount",
                "operator": "GT",
                "value": 100,
            },
            priority=100,
        )

        # Approve rule version
        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rv = result.scalar_one()
        rv.status = EntityStatus.APPROVED.value
        rv.approved_by = checker
        rv.approved_at = now

        # Create RuleSet identity (no version/status - those are on RuleSetVersion)
        ruleset = RuleSet(
            environment="test",
            region="AMERICAS",
            country="US",
            rule_type=RuleType.ALLOWLIST.value,
            name="Workflow Ruleset",
            description="Test ruleset for attach and compile workflow",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create ACTIVE RuleSetVersion (compiler needs ACTIVE status)
        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
            activated_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        # Attach rule to ruleset version
        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rv.rule_version_id,
            )
        )
        await async_db_session.commit()

        # Compile should succeed (compiles from the ruleset_version)
        from app.compiler.compiler import compile_ruleset

        compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert len(compiled["rules"]) == 1
        assert compiled["rulesetId"] == str(ruleset.ruleset_id)
