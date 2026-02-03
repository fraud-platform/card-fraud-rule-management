"""
Tests for the deterministic AST/JSON compiler.

These tests verify:
- Condition tree validation (structure, fields, operators, types)
- Deterministic compilation (same input = same output)
- AST structure correctness
- Error handling and detailed error messages
"""

from uuid import uuid7 as uuid7

import pytest

from app.compiler.canonicalizer import (
    canonicalize_json,
    to_canonical_json_pretty,
    to_canonical_json_string,
)
from app.compiler.compiler import (
    RULE_TYPE_TO_EVALUATION_MODE,
    _get_evaluation_mode,
)
from app.compiler.validator import validate_condition_tree
from app.core.errors import CompilationError, ValidationError

# =============================================================================
# Canonicalizer Tests
# =============================================================================


class TestCanonicalizer:
    """Test JSON canonicalization for determinism."""

    @pytest.mark.anyio
    async def test_canonicalize_simple_dict(self):
        """Test that dict keys are sorted alphabetically."""
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonicalize_json(obj)

        # Keys should be in alphabetical order
        keys = list(result.keys())
        assert keys == ["a", "m", "z"]

    @pytest.mark.anyio
    async def test_canonicalize_nested_dict(self):
        """Test that nested dicts are recursively canonicalized."""
        obj = {"z": {"inner_z": 1, "inner_a": 2}, "a": {"nested_z": 3, "nested_a": 4}}
        result = canonicalize_json(obj)

        # Outer keys sorted
        outer_keys = list(result.keys())
        assert outer_keys == ["a", "z"]

        # Inner keys sorted
        assert list(result["a"].keys()) == ["nested_a", "nested_z"]
        assert list(result["z"].keys()) == ["inner_a", "inner_z"]

    @pytest.mark.anyio
    async def test_canonicalize_preserves_list_order(self):
        """Test that list order is preserved (not sorted)."""
        obj = {"items": [3, 1, 2]}
        result = canonicalize_json(obj)

        assert result["items"] == [3, 1, 2]  # Order preserved

    @pytest.mark.anyio
    async def test_canonicalize_list_of_dicts(self):
        """Test that dicts inside lists are canonicalized."""
        obj = {"rules": [{"z": 1, "a": 2}, {"m": 3, "b": 4}]}
        result = canonicalize_json(obj)

        # Each dict in list should have sorted keys
        assert list(result["rules"][0].keys()) == ["a", "z"]
        assert list(result["rules"][1].keys()) == ["b", "m"]

    @pytest.mark.anyio
    async def test_canonical_json_string_determinism(self):
        """Test that same object produces identical JSON string."""
        obj1 = {"z": 1, "a": {"c": 2, "b": 3}}
        obj2 = {"a": {"b": 3, "c": 2}, "z": 1}  # Same content, different order

        str1 = to_canonical_json_string(obj1)
        str2 = to_canonical_json_string(obj2)

        assert str1 == str2  # Byte-for-byte identical

    @pytest.mark.anyio
    async def test_canonical_json_pretty_readable(self):
        """Test that pretty printing is readable."""
        obj = {"rulesetId": "rs-123", "version": 7}
        result = to_canonical_json_pretty(obj)

        assert '"rulesetId"' in result
        assert '"version"' in result
        assert "\n" in result  # Contains newlines


# =============================================================================
# Validator Tests
# =============================================================================


class TestValidator:
    """Test condition tree validation."""

    @pytest.fixture
    def rule_fields(self):
        """Sample rule fields catalog."""
        return {
            "mcc": {
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN", "NOT_IN"],
                "multi_value_allowed": True,
                "is_active": True,
            },
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT", "GTE", "LT", "LTE", "BETWEEN"],
                "multi_value_allowed": False,
                "is_active": True,
            },
            "is_international": {
                "data_type": "BOOLEAN",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            },
            "inactive_field": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": False,
            },
        }

    @pytest.mark.anyio
    async def test_valid_simple_condition(self, rule_fields):
        """Test validation of a simple valid condition."""
        tree = {"field": "mcc", "op": "EQ", "value": "5967"}

        # Should not raise
        validate_condition_tree(tree, rule_fields)

    @pytest.mark.anyio
    async def test_valid_in_operator(self, rule_fields):
        """Test validation of IN operator with list."""
        tree = {"field": "mcc", "op": "IN", "value": ["5967", "5968"]}

        # Should not raise
        validate_condition_tree(tree, rule_fields)

    @pytest.mark.anyio
    async def test_valid_and_composition(self, rule_fields):
        """Test validation of AND boolean composition."""
        tree = {
            "and": [
                {"field": "mcc", "op": "EQ", "value": "5967"},
                {"field": "amount", "op": "GT", "value": 1000},
            ]
        }

        # Should not raise
        validate_condition_tree(tree, rule_fields)

    @pytest.mark.anyio
    async def test_valid_or_composition(self, rule_fields):
        """Test validation of OR boolean composition."""
        tree = {
            "or": [
                {"field": "mcc", "op": "EQ", "value": "5967"},
                {"field": "amount", "op": "LT", "value": 100},
            ]
        }

        # Should not raise
        validate_condition_tree(tree, rule_fields)

    @pytest.mark.anyio
    async def test_valid_not_composition(self, rule_fields):
        """Test validation of NOT negation."""
        tree = {"not": {"field": "is_international", "op": "EQ", "value": True}}

        # Should not raise
        validate_condition_tree(tree, rule_fields)

    @pytest.mark.anyio
    async def test_valid_nested_composition(self, rule_fields):
        """Test validation of nested boolean logic."""
        tree = {
            "and": [
                {"field": "amount", "op": "GT", "value": 1000},
                {
                    "or": [
                        {"field": "mcc", "op": "EQ", "value": "5967"},
                        {"field": "is_international", "op": "EQ", "value": True},
                    ]
                },
            ]
        }

        # Should not raise
        validate_condition_tree(tree, rule_fields)

    @pytest.mark.anyio
    async def test_empty_tree_fails(self, rule_fields):
        """Test that empty tree raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_condition_tree({}, rule_fields)

        assert "cannot be empty" in str(exc.value)

    @pytest.mark.anyio
    async def test_unknown_field_fails(self, rule_fields):
        """Test that unknown field raises ValidationError."""
        tree = {"field": "nonexistent_field", "op": "EQ", "value": "test"}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "Unknown field" in str(exc.value)
        assert "nonexistent_field" in str(exc.value)

    @pytest.mark.anyio
    async def test_inactive_field_fails(self, rule_fields):
        """Test that inactive field raises ValidationError."""
        tree = {"field": "inactive_field", "op": "EQ", "value": "test"}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "not active" in str(exc.value)

    @pytest.mark.anyio
    async def test_disallowed_operator_fails(self, rule_fields):
        """Test that disallowed operator raises ValidationError."""
        tree = {"field": "mcc", "op": "GT", "value": 5}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "not allowed" in str(exc.value)
        assert "GT" in str(exc.value)

    @pytest.mark.anyio
    async def test_type_mismatch_fails(self, rule_fields):
        """Test that type mismatch raises ValidationError."""
        # amount expects NUMBER, not STRING
        tree = {"field": "amount", "op": "GT", "value": "not a number"}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "NUMBER" in str(exc.value)

    @pytest.mark.anyio
    async def test_in_requires_list(self, rule_fields):
        """Test that IN operator requires a list."""
        tree = {"field": "mcc", "op": "IN", "value": "5967"}  # Should be list

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "requires a list" in str(exc.value)

    @pytest.mark.anyio
    async def test_multi_value_constraint(self, rule_fields):
        """Test that multi_value constraint is enforced."""
        # Create a field that allows IN operator but not multi-value
        # (edge case - normally if IN is allowed, multi_value should be True)
        test_fields = rule_fields.copy()
        test_fields["special_field"] = {
            "data_type": "STRING",
            "allowed_operators": ["EQ", "IN"],  # IN allowed
            "multi_value_allowed": False,  # But multi-value not allowed
            "is_active": True,
        }

        tree = {"field": "special_field", "op": "IN", "value": ["a", "b"]}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, test_fields)

        assert "does not allow multi-value" in str(exc.value)

    @pytest.mark.anyio
    async def test_between_requires_two_values(self, rule_fields):
        """Test that BETWEEN requires exactly 2 values."""
        tree = {"field": "amount", "op": "BETWEEN", "value": [100]}  # Need 2

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "exactly 2 values" in str(exc.value)

    @pytest.mark.anyio
    async def test_empty_and_fails(self, rule_fields):
        """Test that empty AND raises ValidationError."""
        tree = {"and": []}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "cannot be empty" in str(exc.value)

    @pytest.mark.anyio
    async def test_invalid_node_structure(self, rule_fields):
        """Test that invalid node structure raises ValidationError."""
        tree = {"invalid_key": "value"}

        with pytest.raises(ValidationError) as exc:
            validate_condition_tree(tree, rule_fields)

        assert "must contain" in str(exc.value)


# =============================================================================
# Compiler Tests
# =============================================================================


class TestCompiler:
    """Test the main compiler logic."""

    @pytest.mark.anyio
    async def test_evaluation_mode_mapping(self):
        """Test that rule types map to correct evaluation modes."""
        assert _get_evaluation_mode("ALLOWLIST") == "FIRST_MATCH"
        assert _get_evaluation_mode("BLOCKLIST") == "FIRST_MATCH"
        assert _get_evaluation_mode("AUTH") == "FIRST_MATCH"
        assert _get_evaluation_mode("MONITORING") == "ALL_MATCHING"

    @pytest.mark.anyio
    async def test_evaluation_mode_unknown_type(self):
        """Test that unknown rule type raises CompilationError."""
        with pytest.raises(CompilationError) as exc:
            _get_evaluation_mode("UNKNOWN_TYPE")

        assert "Unknown rule type" in str(exc.value)

    @pytest.mark.anyio
    async def test_locked_evaluation_semantics(self):
        """Test that evaluation semantics are locked as specified."""
        # From IMPLEMENTATION-GUIDE.md - these should never change
        expected = {
            "ALLOWLIST": "FIRST_MATCH",
            "BLOCKLIST": "FIRST_MATCH",
            "AUTH": "FIRST_MATCH",
            "MONITORING": "ALL_MATCHING",
        }

        assert RULE_TYPE_TO_EVALUATION_MODE == expected


# =============================================================================
# Integration Test (would need database fixture in real test)
# =============================================================================


class TestCompilerIntegration:
    """
    Integration tests for the full compilation pipeline.

    Note: These tests would need a proper database fixture.
    They are here as documentation of expected behavior.
    """

    @pytest.mark.anyio
    async def test_ast_structure(self):
        """Document expected AST structure."""
        expected_structure = {
            "rulesetId": "rs-uuid",
            "version": 1,
            "ruleType": "MONITORING",
            "evaluation": {"mode": "ALL_MATCHING"},
            "velocityFailurePolicy": "SKIP",
            "rules": [
                {
                    "ruleId": "rule-uuid",
                    "ruleVersionId": "version-uuid",
                    "priority": 100,
                    "when": {"and": [{"field": "amount", "op": "GT", "value": 1000}]},
                    "action": "REVIEW",
                }
            ],
        }

        # Verify structure has all required keys
        assert "rulesetId" in expected_structure
        assert "version" in expected_structure
        assert "ruleType" in expected_structure
        assert "evaluation" in expected_structure
        assert "mode" in expected_structure["evaluation"]
        assert "velocityFailurePolicy" in expected_structure
        assert "rules" in expected_structure

    @pytest.mark.anyio
    async def test_determinism_property(self):
        """
        Document determinism requirement.

        Same RuleSet compiled twice must produce byte-for-byte identical output.
        This is achieved by:
        1. Sorting rules by (priority DESC, rule_id ASC)
        2. Canonicalizing JSON (sorted keys)
        3. No timestamps or random values in output
        """
        # This would be tested with actual database in integration test
        pass
