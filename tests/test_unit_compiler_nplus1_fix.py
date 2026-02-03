"""Tests for compiler N+1 query fix and sorting optimization.

These tests verify that the compiler uses efficient queries.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from sqlalchemy.sql import Select

from app.compiler.compiler import _sort_rules_deterministically
from app.db.models import Rule, RuleVersion


class TestN1QueryFix:
    """Test that the N+1 query fix in _sort_rules_deterministically works correctly."""

    @pytest.mark.anyio
    async def test_sort_rules_uses_join_query(self):
        """Test that sorting uses a single JOIN query instead of N+1 queries."""
        # Create mock rule versions
        rv1 = MagicMock(spec=RuleVersion)
        rv1.rule_version_id = str(uuid7())
        rv1.rule_id = str(uuid7())
        rv1.priority = 100

        rv2 = MagicMock(spec=RuleVersion)
        rv2.rule_version_id = str(uuid7())
        rv2.rule_id = str(uuid7())
        rv2.priority = 200

        rule_versions = [rv1, rv2]

        # Create mock database session
        mock_db = MagicMock()

        # Create mock results that simulate the JOIN query returning tuples
        mock_rule1 = MagicMock(spec=Rule)
        mock_rule1.rule_id = rv1.rule_id

        mock_rule2 = MagicMock(spec=Rule)
        mock_rule2.rule_id = rv2.rule_id

        # Mock the result of the JOIN query - returns tuples of (RuleVersion, Rule)
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([(rv1, mock_rule1), (rv2, mock_rule2)]))
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Call the function
        result = await _sort_rules_deterministically(mock_db, rule_versions)

        # Verify that execute was called once (not N+1 times)
        assert mock_db.execute.call_count == 1

        # Verify the result is sorted correctly (higher priority first)
        assert len(result) == 2
        # rv2 has higher priority (200), so it should come first
        assert result[0][0].priority == 200
        assert result[1][0].priority == 100

    @pytest.mark.anyio
    async def test_sort_rules_empty_list(self):
        """Test that sorting an empty list returns an empty list."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _sort_rules_deterministically(mock_db, [])
        assert result == []

    @pytest.mark.anyio
    async def test_sort_rules_single_item(self):
        """Test that sorting a single rule version works correctly."""
        rv1 = MagicMock(spec=RuleVersion)
        rv1.rule_version_id = str(uuid7())
        rv1.rule_id = str(uuid7())
        rv1.priority = 100

        mock_rule1 = MagicMock(spec=Rule)
        mock_rule1.rule_id = rv1.rule_id

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([(rv1, mock_rule1)]))
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _sort_rules_deterministically(mock_db, [rv1])

        assert len(result) == 1
        assert result[0][0] == rv1

    @pytest.mark.anyio
    async def test_sort_rules_uses_correct_query_structure(self):
        """Test that the function constructs the correct JOIN query."""
        rv1 = MagicMock(spec=RuleVersion)
        rv1.rule_version_id = str(uuid7())
        rv1.rule_id = str(uuid7())
        rv1.priority = 100

        mock_rule1 = MagicMock(spec=Rule)
        mock_rule1.rule_id = rv1.rule_id

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([(rv1, mock_rule1)]))
        mock_db.execute = AsyncMock(return_value=mock_result)

        await _sort_rules_deterministically(mock_db, [rv1])

        # Verify that execute was called with a Select statement
        call_args = mock_db.execute.call_args
        assert call_args is not None
        stmt = call_args[0][0]
        assert isinstance(stmt, Select)

    @pytest.mark.anyio
    async def test_sort_rules_same_priority_sorts_by_rule_id(self):
        """Test that rules with same priority are sorted by rule_id for determinism."""
        # Create rule versions with same priority
        rv1 = MagicMock(spec=RuleVersion)
        rv1.rule_version_id = str(uuid7())
        rv1.rule_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        rv1.priority = 100

        rv2 = MagicMock(spec=RuleVersion)
        rv2.rule_version_id = str(uuid7())
        rv2.rule_id = "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"
        rv2.priority = 100

        rv3 = MagicMock(spec=RuleVersion)
        rv3.rule_version_id = str(uuid7())
        rv3.rule_id = "mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm"
        rv3.priority = 100

        rule_versions = [rv1, rv2, rv3]

        # Create mock rules
        mock_rule1 = MagicMock(spec=Rule)
        mock_rule1.rule_id = rv1.rule_id

        mock_rule2 = MagicMock(spec=Rule)
        mock_rule2.rule_id = rv2.rule_id

        mock_rule3 = MagicMock(spec=Rule)
        mock_rule3.rule_id = rv3.rule_id

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter([(rv1, mock_rule1), (rv2, mock_rule2), (rv3, mock_rule3)])
        )
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _sort_rules_deterministically(mock_db, rule_versions)

        # All have same priority, so should be sorted by rule_id ascending
        assert len(result) == 3
        assert result[0][1].rule_id == rv1.rule_id  # "a..." comes first
        assert result[1][1].rule_id == rv3.rule_id  # "m..." comes second
        assert result[2][1].rule_id == rv2.rule_id  # "z..." comes last

    @pytest.mark.anyio
    async def test_sort_rules_mixed_priorities(self):
        """Test sorting with mixed priorities and rule_ids."""
        # Create rule versions with different priorities
        rv1 = MagicMock(spec=RuleVersion)  # High priority, id "z"
        rv1.rule_version_id = str(uuid7())
        rv1.rule_id = "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"
        rv1.priority = 300

        rv2 = MagicMock(spec=RuleVersion)  # Low priority, id "a"
        rv2.rule_version_id = str(uuid7())
        rv2.rule_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        rv2.priority = 100

        rv3 = MagicMock(spec=RuleVersion)  # Medium priority, id "m"
        rv3.rule_version_id = str(uuid7())
        rv3.rule_id = "mmmmmmmm-mmmm-mmmm-mmmm-mmmmmmmmmmmm"
        rv3.priority = 200

        rule_versions = [rv1, rv2, rv3]

        # Create mock rules
        mock_rule1 = MagicMock(spec=Rule)
        mock_rule1.rule_id = rv1.rule_id

        mock_rule2 = MagicMock(spec=Rule)
        mock_rule2.rule_id = rv2.rule_id

        mock_rule3 = MagicMock(spec=Rule)
        mock_rule3.rule_id = rv3.rule_id

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(
            return_value=iter([(rv1, mock_rule1), (rv2, mock_rule2), (rv3, mock_rule3)])
        )
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _sort_rules_deterministically(mock_db, rule_versions)

        # Should be sorted by priority DESC, then rule_id ASC
        assert len(result) == 3
        assert result[0][0].priority == 300  # rv1 - highest priority
        assert result[1][0].priority == 200  # rv3 - medium priority
        assert result[2][0].priority == 100  # rv2 - lowest priority

    @pytest.mark.anyio
    async def test_sort_rules_only_one_query_executed(self):
        """Critical test: Verify that only ONE query is executed regardless of rule count."""
        # Create many rule versions
        rule_versions = []
        mock_rules = []
        for i in range(100):  # 100 rules
            rv = MagicMock(spec=RuleVersion)
            rv.rule_version_id = str(uuid7())
            rv.rule_id = str(uuid7())
            rv.priority = i
            rule_versions.append(rv)

            mock_rule = MagicMock(spec=Rule)
            mock_rule.rule_id = rv.rule_id
            mock_rules.append((rv, mock_rule))

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(mock_rules))
        mock_db.execute = AsyncMock(return_value=mock_result)

        await _sort_rules_deterministically(mock_db, rule_versions)

        # CRITICAL: Only ONE query should be executed (the JOIN query)
        # If this were N+1, we'd see 101 queries (1 for rule versions + 100 for rules)
        assert mock_db.execute.call_count == 1, (
            f"Expected 1 query but {mock_db.execute.call_count} were executed. "
            "This indicates the N+1 query fix is not working!"
        )
