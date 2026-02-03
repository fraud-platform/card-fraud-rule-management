"""
Integration tests for the compiler pipeline.

Tests cover:
- Full compile_ruleset() call with database
- Determinism verification (compile twice, compare byte-for-byte)
- Compiled AST retrieval via API
- Compilation with non-approved rules
- Compilation with deleted field references
- Empty ruleset compilation
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.compiler import compile_ruleset
from app.core.errors import CompilationError, NotFoundError
from app.db.models import RuleSet, RuleSetVersion, RuleSetVersionRule, RuleVersion
from app.domain.enums import EntityStatus, RuleType

# =============================================================================
# Helper functions for async database operations
# =============================================================================


async def create_rule_field_in_db_async(session: AsyncSession, **kwargs):
    """Helper to create a RuleField directly in the database (async version)."""
    import uuid

    from sqlalchemy import func

    from app.db.models import RuleField

    # Get next field_id if not provided
    result = await session.execute(select(func.max(RuleField.field_id)))
    max_id = result.scalar_one_or_none()
    next_id = (max_id or 26) + 1

    defaults = {
        "field_key": f"test_field_{uuid.uuid4().hex[:8]}",
        "field_id": kwargs.get("field_id", next_id),
        "display_name": "Test Field",
        "description": None,
        "data_type": "STRING",
        "allowed_operators": ["EQ"],
        "multi_value_allowed": False,
        "is_sensitive": False,
        "current_version": 1,
        "version": 1,
        "created_by": "test@example.com",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    field_key = defaults["field_key"]

    # Check if field already exists
    result = await session.execute(select(RuleField).where(RuleField.field_key == field_key))
    existing = result.scalar_one_or_none()
    if existing:
        await session.refresh(existing)
        return existing

    field = RuleField(**defaults)
    session.add(field)
    await session.flush()
    await session.refresh(field)
    return field


async def create_rule_in_db_async(session: AsyncSession, created_by: str = "test-user", **kwargs):
    """Helper to create a Rule with initial version in the database (async version)."""
    import uuid

    from app.db.models import Rule, RuleVersion
    from app.domain.enums import EntityStatus, RuleType

    rule_id = kwargs.get("rule_id", uuid.uuid4())

    rule_defaults = {
        "rule_id": rule_id,
        "rule_name": "Test Rule",
        "description": "Test Description",
        "rule_type": RuleType.ALLOWLIST.value,
        "current_version": 1,
        "status": EntityStatus.DRAFT.value,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    for key in ["rule_name", "description", "rule_type", "status"]:
        if key in kwargs:
            rule_defaults[key] = kwargs.pop(key)

    rule = Rule(**rule_defaults)
    session.add(rule)

    rule_type_for_action = rule_defaults.get("rule_type", RuleType.ALLOWLIST.value)
    action_map = {
        RuleType.ALLOWLIST.value: "APPROVE",
        RuleType.BLOCKLIST.value: "DECLINE",
        RuleType.AUTH.value: "APPROVE",
        RuleType.MONITORING.value: "REVIEW",
    }
    default_action = action_map.get(rule_type_for_action, "REVIEW")

    version_defaults = {
        "rule_version_id": uuid.uuid4(),
        "rule_id": rule_id,
        "version": 1,
        "condition_tree": {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
        "action": kwargs.pop("action", default_action),
        "priority": kwargs.pop("priority", 100),
        "status": EntityStatus.DRAFT.value,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
    }
    version_defaults.update(kwargs)

    version = RuleVersion(**version_defaults)
    session.add(version)
    await session.flush()
    await session.refresh(rule)
    await session.refresh(version)
    return rule


# =============================================================================
# Test Classes
# =============================================================================


class TestCompilerIntegration:
    """Integration tests for the full compiler pipeline."""

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_approved_ruleset_succeeds(self, async_db_session: AsyncSession):
        """Test that compiling an approved ruleset with approved rules succeeds."""
        now = datetime.now(UTC)
        checker = "checker-user"

        # Create rule fields
        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Transaction Amount",
            data_type="NUMBER",
            allowed_operators=["EQ", "GT", "LT", "GTE", "LTE", "BETWEEN"],
        )
        await create_rule_field_in_db_async(
            async_db_session,
            field_key="currency",
            display_name="Currency",
            data_type="STRING",
            allowed_operators=["EQ", "IN"],
            multi_value_allowed=True,
        )

        # Create rules
        rule1 = await create_rule_in_db_async(
            async_db_session,
            rule_name="High Value Transaction",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={
                "type": "CONDITION",
                "field": "amount",
                "operator": "GT",
                "value": 1000,
            },
            priority=100,
        )

        rule2 = await create_rule_in_db_async(
            async_db_session,
            rule_name="USD Transaction",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={
                "type": "CONDITION",
                "field": "currency",
                "operator": "EQ",
                "value": "USD",
            },
            priority=50,
        )

        # Get rule versions and mark as APPROVED
        stmt = select(RuleVersion).where(RuleVersion.rule_id.in_([rule1.rule_id, rule2.rule_id]))
        result = await async_db_session.execute(stmt)
        rule_versions = result.scalars().all()
        for rv in rule_versions:
            rv.status = EntityStatus.APPROVED.value
            rv.approved_by = checker
            rv.approved_at = now
        await async_db_session.flush()

        # Create RuleSet identity
        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Test Ruleset",
            description="Test ruleset for compilation",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create RuleSetVersion with ACTIVE status
        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        # Attach rule versions to ruleset version
        for rv in rule_versions:
            async_db_session.add(
                RuleSetVersionRule(
                    ruleset_version_id=ruleset_version.ruleset_version_id,
                    rule_version_id=rv.rule_version_id,
                )
            )
        await async_db_session.flush()

        # Compile
        compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        # Verify structure
        assert "rulesetId" in compiled
        assert "version" in compiled
        assert "ruleType" in compiled
        assert "evaluation" in compiled
        assert "velocityFailurePolicy" in compiled
        assert "rules" in compiled

        assert compiled["rulesetId"] == str(ruleset.ruleset_id)
        assert compiled["version"] == 1
        assert compiled["ruleType"] == RuleType.ALLOWLIST.value
        assert compiled["evaluation"]["mode"] == "FIRST_MATCH"
        assert compiled["velocityFailurePolicy"] == "SKIP"

        # Rules should be sorted by priority DESC, rule_id ASC
        assert len(compiled["rules"]) == 2
        assert compiled["rules"][0]["priority"] >= compiled["rules"][1]["priority"]

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_determinism(self, async_db_session: AsyncSession):
        """Test that compiling twice produces identical output."""
        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Test Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
            priority=100,
        )

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rule_version = result.scalar_one()
        rule_version.status = EntityStatus.APPROVED.value
        rule_version.approved_by = checker
        rule_version.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Determinism Test",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rule_version.rule_version_id,
            )
        )
        await async_db_session.flush()

        compiled1 = await compile_ruleset(ruleset.ruleset_id, async_db_session)
        compiled2 = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        json1 = json.dumps(compiled1, sort_keys=True)
        json2 = json.dumps(compiled2, sort_keys=True)
        assert json1 == json2

        bytes1 = json.dumps(compiled1, separators=(",", ":")).encode("utf-8")
        bytes2 = json.dumps(compiled2, separators=(",", ":")).encode("utf-8")
        assert bytes1 == bytes2

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_fails_with_draft_ruleset(self, async_db_session: AsyncSession):
        """Test that compilation fails with DRAFT status ruleset."""
        now = datetime.now(UTC)

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Test Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
            priority=100,
        )

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rule_version = result.scalar_one()
        rule_version.status = EntityStatus.APPROVED.value
        rule_version.approved_by = "checker"
        rule_version.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Draft Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.DRAFT.value,
            created_by="test-user",
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rule_version.rule_version_id,
            )
        )
        await async_db_session.flush()

        with pytest.raises(NotFoundError) as exc_info:
            await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert "active" in str(exc_info.value).lower() or "found" in str(exc_info.value).lower()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_fails_with_non_approved_rule_versions(
        self, async_db_session: AsyncSession
    ):
        """Test that compilation fails with non-APPROVED rule versions."""
        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Test Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
            priority=100,
        )
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Test Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rule_version = result.scalar_one()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rule_version.rule_version_id,
            )
        )
        await async_db_session.flush()

        with pytest.raises(CompilationError) as exc_info:
            await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert "non-APPROVED" in str(exc_info.value)

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_nonexistent_ruleset(self, async_db_session: AsyncSession):
        """Test that compiling a non-existent ruleset raises NotFoundError."""
        fake_id = uuid4()

        with pytest.raises(NotFoundError) as exc_info:
            await compile_ruleset(fake_id, async_db_session)

        assert "ruleset" in str(exc_info.value).lower() or "found" in str(exc_info.value).lower()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_empty_ruleset(self, async_db_session: AsyncSession):
        """Test that compiling an empty ruleset succeeds."""
        now = datetime.now(UTC)
        checker = "checker-user"

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Empty Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert compiled["rules"] == []
        assert compiled["rulesetId"] == str(ruleset.ruleset_id)

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_with_unknown_field_allowed(self, async_db_session: AsyncSession):
        """Test that compilation allows unknown fields in lenient mode."""
        now = datetime.now(UTC)
        checker = "checker-user"

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Runtime Field Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={
                "type": "CONDITION",
                "field": "runtime_field_not_in_catalog",
                "operator": "EQ",
                "value": "test",
            },
            priority=100,
        )

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rule_version = result.scalar_one()
        rule_version.status = EntityStatus.APPROVED.value
        rule_version.approved_by = checker
        rule_version.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Runtime Field Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rule_version.rule_version_id,
            )
        )
        await async_db_session.flush()

        compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert len(compiled["rules"]) == 1
        assert compiled["rules"][0]["when"]["field"] == "runtime_field_not_in_catalog"

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_with_invalid_condition_tree(self, async_db_session: AsyncSession):
        """Test that compilation fails with invalid condition tree."""
        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Invalid Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={
                "type": "CONDITION",
                "field": "amount",
                "operator": "EQ",
                "value": "not a number",
            },
            priority=100,
        )

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rule_version = result.scalar_one()
        rule_version.status = EntityStatus.APPROVED.value
        rule_version.approved_by = checker
        rule_version.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Invalid Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rule_version.rule_version_id,
            )
        )
        await async_db_session.flush()

        with pytest.raises(CompilationError) as exc_info:
            await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert "validation" in str(exc_info.value).lower()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_ruleset_deterministic_sorting(self, async_db_session: AsyncSession):
        """Test that rules are sorted deterministically."""
        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        rule1 = await create_rule_in_db_async(
            async_db_session,
            rule_name="Low Priority",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
            priority=10,
        )

        rule2 = await create_rule_in_db_async(
            async_db_session,
            rule_name="High Priority",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 200},
            priority=100,
        )

        rule3 = await create_rule_in_db_async(
            async_db_session,
            rule_name="Medium Priority",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 150},
            priority=50,
        )

        stmt = select(RuleVersion).where(
            RuleVersion.rule_id.in_([rule1.rule_id, rule2.rule_id, rule3.rule_id])
        )
        result = await async_db_session.execute(stmt)
        rule_versions = result.scalars().all()
        for rv in rule_versions:
            rv.status = EntityStatus.APPROVED.value
            rv.approved_by = checker
            rv.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Sort Test",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        for rule in [rule1, rule3, rule2]:
            stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
            result = await async_db_session.execute(stmt)
            rv = result.scalar_one()
            async_db_session.add(
                RuleSetVersionRule(
                    ruleset_version_id=ruleset_version.ruleset_version_id,
                    rule_version_id=rv.rule_version_id,
                )
            )
        await async_db_session.flush()

        compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        priorities = [r["priority"] for r in compiled["rules"]]
        assert priorities == sorted(priorities, reverse=True)

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_different_rule_types(self, async_db_session: AsyncSession):
        """Test compilation with different rule types."""
        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        for rule_type, expected_mode in [
            (RuleType.ALLOWLIST.value, "FIRST_MATCH"),
            (RuleType.BLOCKLIST.value, "FIRST_MATCH"),
            (RuleType.AUTH.value, "FIRST_MATCH"),
            (RuleType.MONITORING.value, "ALL_MATCHING"),
        ]:
            rule = await create_rule_in_db_async(
                async_db_session,
                rule_name=f"{rule_type} Rule",
                rule_type=rule_type,
                condition_tree={
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                priority=100,
            )

            stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
            result = await async_db_session.execute(stmt)
            rv = result.scalar_one()
            rv.status = EntityStatus.APPROVED.value
            rv.approved_by = checker
            rv.approved_at = now
            await async_db_session.flush()

            ruleset = RuleSet(
                environment="local",
                region="INDIA",
                country="IN",
                rule_type=rule_type,
                name=f"{rule_type} Ruleset",
                created_by="test-user",
            )
            async_db_session.add(ruleset)
            await async_db_session.flush()

            ruleset_version = RuleSetVersion(
                ruleset_id=ruleset.ruleset_id,
                version=1,
                status=EntityStatus.ACTIVE.value,
                activated_at=datetime.now(UTC),
                created_by="test-user",
                approved_by=checker,
                approved_at=now,
            )
            async_db_session.add(ruleset_version)
            await async_db_session.flush()

            async_db_session.add(
                RuleSetVersionRule(
                    ruleset_version_id=ruleset_version.ruleset_version_id,
                    rule_version_id=rv.rule_version_id,
                )
            )
            await async_db_session.flush()

            compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

            assert compiled["evaluation"]["mode"] == expected_mode
            assert compiled["ruleType"] == rule_type

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_compile_with_complex_condition_tree(self, async_db_session: AsyncSession):
        """Test compilation with complex nested condition tree."""
        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT", "LT"],
        )
        await create_rule_field_in_db_async(
            async_db_session,
            field_key="currency",
            display_name="Currency",
            data_type="STRING",
            allowed_operators=["EQ", "IN"],
            multi_value_allowed=True,
        )

        complex_tree = {
            "type": "OR",
            "conditions": [
                {
                    "type": "AND",
                    "conditions": [
                        {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 1000},
                        {
                            "type": "CONDITION",
                            "field": "currency",
                            "operator": "IN",
                            "value": ["USD", "EUR"],
                        },
                    ],
                },
                {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 5000},
            ],
        }

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Complex Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree=complex_tree,
            priority=100,
        )

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rv = result.scalar_one()
        rv.status = EntityStatus.APPROVED.value
        rv.approved_by = checker
        rv.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Complex Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rv.rule_version_id,
            )
        )
        await async_db_session.flush()

        compiled = await compile_ruleset(ruleset.ruleset_id, async_db_session)

        assert compiled["rules"][0]["when"] == complex_tree


class TestCompiledAstRetrieval:
    """Tests for retrieving compiled AST via the repository."""

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_get_compiled_ast_after_compile(self, async_db_session: AsyncSession):
        """Test retrieving compiled AST after compilation."""
        from app.repos.ruleset_repo import compile_ruleset_version

        now = datetime.now(UTC)
        checker = "checker-user"

        await create_rule_field_in_db_async(
            async_db_session,
            field_key="amount",
            display_name="Amount",
            data_type="NUMBER",
            allowed_operators=["GT"],
        )

        rule = await create_rule_in_db_async(
            async_db_session,
            rule_name="Test Rule",
            rule_type=RuleType.ALLOWLIST.value,
            condition_tree={"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
            priority=100,
        )

        stmt = select(RuleVersion).where(RuleVersion.rule_id == rule.rule_id)
        result = await async_db_session.execute(stmt)
        rv = result.scalar_one()
        rv.status = EntityStatus.APPROVED.value
        rv.approved_by = checker
        rv.approved_at = now
        await async_db_session.flush()

        ruleset = RuleSet(
            environment="local",
            region="INDIA",
            country="IN",
            rule_type=RuleType.ALLOWLIST.value,
            name="Test Ruleset",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status=EntityStatus.ACTIVE.value,
            activated_at=datetime.now(UTC),
            created_by="test-user",
            approved_by=checker,
            approved_at=now,
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        async_db_session.add(
            RuleSetVersionRule(
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_id=rv.rule_version_id,
            )
        )
        await async_db_session.flush()

        result = await compile_ruleset_version(
            async_db_session,
            ruleset_version_id=ruleset_version.ruleset_version_id,
            invoked_by="test-user",
        )

        assert "compiled_ast" in result
        assert "rulesetId" in result["compiled_ast"]
        assert result["compiled_ast"]["rulesetId"] == str(ruleset.ruleset_id)

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_get_compiled_ast_not_found(self, async_db_session: AsyncSession):
        """Test retrieving AST for ruleset that hasn't been compiled."""
        from app.repos.ruleset_repo import get_compiled_ast

        fake_id = uuid4()

        with pytest.raises(NotImplementedError) as exc_info:
            await get_compiled_ast(async_db_session, ruleset_id=fake_id)

        assert (
            "deprecated" in str(exc_info.value).lower()
            or "compile_ruleset_version" in str(exc_info.value).lower()
        )
