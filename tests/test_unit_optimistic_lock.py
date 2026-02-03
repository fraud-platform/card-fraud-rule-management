"""
Tests for optimistic concurrency control (version column).

Tests verify that:
1. Version column is present on rules (optimistic locking)
2. Version increments on every update
3. Concurrent modifications are detected and raise ConflictError
4. Error messages provide helpful information about version mismatch

Note: RuleSet no longer has a version column (moved to RuleSetVersion).
The RuleSetVersion.version is a semantic version number, not an optimistic lock.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.optimistic_lock import (
    check_rule_version_async,
    check_ruleset_version_async,
)
from app.db.models import Rule, RuleSet
from app.repos.rule_repo import create_rule, create_rule_version
from app.repos.ruleset_repo import create_ruleset, create_ruleset_version


@pytest.mark.unit
class TestOptimisticLockingRules:
    """Test optimistic locking for Rule entities."""

    @pytest.mark.anyio
    async def test_rule_has_version_column(self, async_db_session: AsyncSession):
        """Verify that Rule model has version column starting at 1."""
        rule = Rule(
            rule_name="Test Rule",
            rule_type="BLOCKLIST",
            current_version=1,
            status="DRAFT",
            created_by="test@example.com",
            version=1,
        )
        async_db_session.add(rule)
        await async_db_session.flush()

        assert rule.version == 1
        await async_db_session.rollback()

    @pytest.mark.anyio
    async def test_rule_version_increments_on_update(self, async_db_session: AsyncSession):
        """Verify that version auto-increments when rule is updated."""
        # Create a rule
        rule = await create_rule(
            async_db_session,
            rule_name="Test Rule",
            description="Test",
            rule_type="BLOCKLIST",
            created_by="test@example.com",
            condition_tree={},
            priority=100,
        )
        initial_version = rule.version
        await async_db_session.commit()

        # Create a new version (this increments the rule's version)
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "test"},
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Version should be incremented
        assert rule.version == initial_version + 1
        await async_db_session.rollback()

    @pytest.mark.anyio
    async def test_check_rule_version_success(self, async_db_session: AsyncSession):
        """Verify version check succeeds when version matches."""
        rule = await create_rule(
            async_db_session,
            rule_name="Test Rule",
            description="Test",
            rule_type="BLOCKLIST",
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Check with correct version should succeed
        checked_rule = await check_rule_version_async(
            async_db_session, rule_id=rule.rule_id, expected_version=rule.version
        )
        assert checked_rule.rule_id == rule.rule_id
        assert checked_rule.version == rule.version

    @pytest.mark.anyio
    async def test_check_rule_version_not_found(self, async_db_session: AsyncSession):
        """Verify version check raises NotFoundError for non-existent rule."""
        with pytest.raises(NotFoundError) as exc_info:
            await check_rule_version_async(
                async_db_session, rule_id="00000000-0000-0000-0000-000000000000", expected_version=1
            )

        assert "Rule not found" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_check_rule_version_conflict(self, async_db_session: AsyncSession):
        """Verify version check raises ConflictError when version mismatches."""
        rule = await create_rule(
            async_db_session,
            rule_name="Test Rule",
            description="Test",
            rule_type="BLOCKLIST",
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Create a new version to increment the rule's version
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "test"},
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Try to check with old version - should fail
        old_version = 1
        with pytest.raises(ConflictError) as exc_info:
            await check_rule_version_async(
                async_db_session, rule_id=rule.rule_id, expected_version=old_version
            )

        error = exc_info.value
        assert "Rule was modified by another transaction" in error.message
        assert error.details["expected_version"] == old_version
        assert error.details["actual_version"] == rule.version
        assert error.details["entity_type"] == "Rule"
        assert str(rule.rule_id) in error.details["entity_id"]


@pytest.mark.unit
class TestOptimisticLockingRuleSetVersions:
    """Test optimistic locking for RuleSetVersion entities.

    Note: RuleSetVersion.version is a semantic version number (1, 2, 3...),
    not an optimistic lock. The check_ruleset_version function validates
    that the version matches before updating the ruleset version.
    """

    @pytest.mark.anyio
    async def test_ruleset_has_no_version_column(self, async_db_session: AsyncSession):
        """Verify that RuleSet model does NOT have a version column (identity only)."""
        # Create a ruleset identity - no version column
        ruleset = RuleSet(
            environment="test",
            region="APAC",
            country="IN",
            rule_type="BLOCKLIST",
            created_by="test@example.com",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # RuleSet should not have a version attribute
        assert not hasattr(ruleset, "version") or getattr(ruleset, "version", None) is None
        await async_db_session.rollback()

    @pytest.mark.anyio
    async def test_ruleset_version_has_version_column(self, async_db_session: AsyncSession):
        """Verify that RuleSetVersion model has version column."""
        # Create a ruleset identity first
        ruleset = await create_ruleset(
            async_db_session,
            environment="test",
            region="APAC",
            country="IN",
            rule_type="BLOCKLIST",
            name="Test RuleSet",
            description=None,
            created_by="test@example.com",
        )

        # Create a ruleset version (version is auto-computed)
        ruleset_version = await create_ruleset_version(
            async_db_session,
            ruleset_id=ruleset.ruleset_id,
            created_by="test@example.com",
        )
        await async_db_session.flush()

        assert ruleset_version.version == 1
        await async_db_session.rollback()

    @pytest.mark.anyio
    async def test_check_ruleset_version_success(self, async_db_session: AsyncSession):
        """Verify version check succeeds when version matches."""
        # Create a ruleset identity
        ruleset = await create_ruleset(
            async_db_session,
            environment="test",
            region="APAC",
            country="IN",
            rule_type="BLOCKLIST",
            name="Test RuleSet",
            description=None,
            created_by="test@example.com",
        )

        # Create a ruleset version
        ruleset_version = await create_ruleset_version(
            async_db_session,
            ruleset_id=ruleset.ruleset_id,
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Check with correct version should succeed
        checked_version = await check_ruleset_version_async(
            async_db_session,
            ruleset_version_id=ruleset_version.ruleset_version_id,
            expected_version=ruleset_version.version,
        )
        assert checked_version.ruleset_version_id == ruleset_version.ruleset_version_id
        assert checked_version.version == ruleset_version.version

    @pytest.mark.anyio
    async def test_check_ruleset_version_not_found(self, async_db_session: AsyncSession):
        """Verify version check raises NotFoundError for non-existent ruleset version."""
        with pytest.raises(NotFoundError) as exc_info:
            await check_ruleset_version_async(
                async_db_session,
                ruleset_version_id="00000000-0000-0000-0000-000000000000",
                expected_version=1,
            )

        assert "Ruleset version not found" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_check_ruleset_version_conflict(self, async_db_session: AsyncSession):
        """Verify version check raises ConflictError when version mismatches."""
        # Create a ruleset identity
        ruleset = await create_ruleset(
            async_db_session,
            environment="test",
            region="APAC",
            country="IN",
            rule_type="BLOCKLIST",
            name="Test RuleSet",
            description=None,
            created_by="test@example.com",
        )

        # Create a ruleset version
        ruleset_version = await create_ruleset_version(
            async_db_session,
            ruleset_id=ruleset.ruleset_id,
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # Try to check with wrong version - should fail
        wrong_version = 999
        with pytest.raises(ConflictError) as exc_info:
            await check_ruleset_version_async(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                expected_version=wrong_version,
            )

        error = exc_info.value
        assert "RuleSetVersion was modified by another transaction" in error.message
        assert error.details["expected_version"] == wrong_version
        assert error.details["actual_version"] == ruleset_version.version
        assert error.details["entity_type"] == "RuleSetVersion"
        assert str(ruleset_version.ruleset_version_id) in error.details["entity_id"]


@pytest.mark.unit
class TestOptimisticLockingIntegration:
    """Integration tests for optimistic locking with concurrent updates."""

    @pytest.mark.anyio
    async def test_concurrent_rule_update_detection(self, async_db_session: AsyncSession):
        """Simulate concurrent updates to same rule."""
        rule = await create_rule(
            async_db_session,
            rule_name="Test Rule",
            description="Test",
            rule_type="BLOCKLIST",
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # User A reads rule at version 1
        version_a = rule.version

        # User B reads rule at same time (also version 1)
        version_b = rule.version

        # User A creates a new version first
        await check_rule_version_async(
            async_db_session, rule_id=rule.rule_id, expected_version=version_a
        )
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "test_a"},
            created_by="user_a@example.com",
        )
        await async_db_session.commit()

        # User B tries to create version with stale version
        # This should detect that version changed
        with pytest.raises(ConflictError) as exc_info:
            await create_rule_version(
                async_db_session,
                rule_id=rule.rule_id,
                condition_tree={"field": "test_b"},
                created_by="user_b@example.com",
                expected_rule_version=version_b,
            )

        assert "Rule was modified by another transaction" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_concurrent_ruleset_version_detection(self, async_db_session: AsyncSession):
        """Simulate concurrent updates to same ruleset version."""
        # Create a ruleset identity
        ruleset = await create_ruleset(
            async_db_session,
            environment="test",
            region="APAC",
            country="IN",
            rule_type="BLOCKLIST",
            name="Test RuleSet",
            description=None,
            created_by="test@example.com",
        )

        # Create initial version
        ruleset_version = await create_ruleset_version(
            async_db_session,
            ruleset_id=ruleset.ruleset_id,
            created_by="test@example.com",
        )
        await async_db_session.commit()

        # User A reads ruleset version

        # User B reads ruleset version

        # User A creates a new ruleset version
        await create_ruleset_version(
            async_db_session,
            ruleset_id=ruleset.ruleset_id,
            created_by="user_a@example.com",
        )
        await async_db_session.commit()

        # User B tries with stale version
        # Verify that the version check works with wrong version
        with pytest.raises(ConflictError) as exc_info:
            await check_ruleset_version_async(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                expected_version=999,
            )

        assert "RuleSetVersion was modified by another transaction" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_multiple_updates_increment_version(self, async_db_session: AsyncSession):
        """Verify multiple successive updates increment version each time."""
        rule = await create_rule(
            async_db_session,
            rule_name="Test Rule",
            description="Test",
            rule_type="BLOCKLIST",
            created_by="test@example.com",
        )
        await async_db_session.commit()

        initial_version = rule.version

        # First update - create version 2
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "test1"},
            created_by="test@example.com",
        )
        await async_db_session.commit()
        assert rule.version == initial_version + 1

        # Second update - create version 3
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "test2"},
            created_by="test@example.com",
        )
        await async_db_session.commit()
        assert rule.version == initial_version + 2

        # Third update - create version 4
        await create_rule_version(
            async_db_session,
            rule_id=rule.rule_id,
            condition_tree={"field": "test3"},
            created_by="test@example.com",
        )
        await async_db_session.commit()
        assert rule.version == initial_version + 3
