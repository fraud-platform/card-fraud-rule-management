"""
Unit tests for validator functions in app.core.validators and app.db.validators.

Tests cover:
- validate_uuid
- validate_uuid_string (app.db.validators)
- validate_condition_tree_depth
- validate_condition_tree_node_count
- ConditionTreeValidator class
- Edge cases and error conditions
"""

import uuid

import pytest

from app.core.validators import (
    validate_condition_tree_depth,
    validate_condition_tree_node_count,
    validate_uuid,
)
from app.db.validators import validate_uuid_string


class TestValidateUUID:
    """Tests for validate_uuid function."""

    @pytest.mark.anyio
    async def test_valid_uuid_accepted(self):
        """Test that valid UUID format is accepted."""
        uuid_value = "01912345-1234-1234-1234-123456789abc"
        result = validate_uuid(uuid_value)
        assert result == uuid_value

    @pytest.mark.anyio
    async def test_valid_uuid_lowercase_accepted(self):
        """Test that lowercase UUID is accepted."""
        uuid_value = "01912345-1234-1234-1234-123456789abc"
        result = validate_uuid(uuid_value.lower())
        assert result == uuid_value.lower()

    @pytest.mark.anyio
    async def test_invalid_uuid_too_short(self):
        """Test that UUID too short is rejected."""
        with pytest.raises(ValueError, match="must be a valid UUID format"):
            validate_uuid("01912345-1234")

    @pytest.mark.anyio
    async def test_invalid_uuid_too_long(self):
        """Test that UUID with extra characters is rejected."""
        with pytest.raises(ValueError, match="must be a valid UUID format"):
            validate_uuid("01912345-1234-1234-1234-123456789abc-extra")

    @pytest.mark.anyio
    async def test_invalid_uuid_missing_hyphens(self):
        """Test that UUID without hyphens is rejected."""
        with pytest.raises(ValueError, match="must be a valid UUID format"):
            validate_uuid("01912345123412341234123456789abc")

    @pytest.mark.anyio
    async def test_invalid_uuid_not_string(self):
        """Test that non-string UUID is rejected."""
        with pytest.raises(ValueError, match="must be a string"):
            validate_uuid(12345)

    @pytest.mark.anyio
    async def test_invalid_uuid_none(self):
        """Test that None UUID is rejected."""
        with pytest.raises(ValueError, match="must be a string"):
            validate_uuid(None)

    @pytest.mark.anyio
    async def test_invalid_uuid_empty_string(self):
        """Test that empty string UUID is rejected."""
        with pytest.raises(ValueError, match="must be a valid UUID format"):
            validate_uuid("")

    @pytest.mark.anyio
    async def test_invalid_uuid_special_chars(self):
        """Test that UUID with special characters is rejected."""
        with pytest.raises(ValueError, match="must be a valid UUID format"):
            validate_uuid("01912345-1234-1234-1234-123456789ab@")

    @pytest.mark.anyio
    async def test_validate_uuid_with_custom_field_name(self):
        """Test that custom field name is used in error message."""
        with pytest.raises(ValueError, match="rule_id must be a valid UUID format"):
            validate_uuid("invalid", field_name="rule_id")


class TestValidateConditionTreeDepth:
    """Tests for validate_condition_tree_depth function."""

    @pytest.mark.anyio
    async def test_should_accept_simple_condition(self):
        """Test that a simple condition node passes depth validation."""
        condition = {
            "type": "CONDITION",
            "field": "amount",
            "operator": "GT",
            "value": 100,
        }

        # Should not raise any exception
        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_accept_shallow_logical_tree(self):
        """Test that a shallow logical tree passes depth validation."""
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                {
                    "type": "CONDITION",
                    "field": "country",
                    "operator": "EQ",
                    "value": "US",
                },
            ],
        }

        # Should not raise any exception
        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_accept_tree_at_max_depth(self):
        """Test that a tree exactly at max depth passes validation."""
        # Build a tree with exactly 10 levels (depth 0 to 9)
        condition = {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100}

        for _ in range(9):
            condition = {
                "type": "LOGICAL",
                "operator": "AND",
                "conditions": [condition],
            }

        # Should not raise any exception (depth 9 is OK for max_depth=10)
        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_reject_tree_exceeding_max_depth(self):
        """Test that a tree exceeding max depth fails validation."""
        # Build a tree with 12 levels (depth 0 to 11)
        condition = {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100}

        for _ in range(11):
            condition = {
                "type": "LOGICAL",
                "operator": "AND",
                "conditions": [condition],
            }

        # Should raise ValueError (depth 10 exceeds max_depth=10)
        with pytest.raises(ValueError, match="Condition tree exceeds maximum depth of 10"):
            validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_accept_custom_max_depth(self):
        """Test that custom max_depth parameter is respected."""
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {
                    "type": "LOGICAL",
                    "operator": "AND",
                    "conditions": [
                        {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100}
                    ],
                }
            ],
        }

        # Should pass with max_depth=5
        validate_condition_tree_depth(condition, max_depth=5)

        # Should fail with max_depth=1
        with pytest.raises(ValueError, match="Condition tree exceeds maximum depth of 1"):
            validate_condition_tree_depth(condition, max_depth=1)

    @pytest.mark.anyio
    async def test_should_handle_empty_logical_node(self):
        """Test that a logical node with no conditions is handled correctly."""
        condition = {"type": "LOGICAL", "operator": "AND", "conditions": []}

        # Should not raise any exception (no children to validate)
        validate_condition_tree_depth(condition, max_depth=10)


class TestValidateConditionTreeNodeCount:
    """Tests for validate_condition_tree_node_count function."""

    @pytest.mark.anyio
    async def test_should_count_single_node(self):
        """Test that a single condition node is counted correctly."""
        condition = {
            "type": "CONDITION",
            "field": "amount",
            "operator": "GT",
            "value": 100,
        }

        # Should not raise any exception (1 node <= 1000)
        validate_condition_tree_node_count(condition, max_nodes=1000)

    @pytest.mark.anyio
    async def test_should_count_logical_node_with_children(self):
        """Test that logical node and children are all counted."""
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                {
                    "type": "CONDITION",
                    "field": "country",
                    "operator": "EQ",
                    "value": "US",
                },
            ],
        }

        # Should not raise any exception (3 nodes: 1 logical + 2 conditions)
        validate_condition_tree_node_count(condition, max_nodes=1000)

    @pytest.mark.anyio
    async def test_should_count_deep_tree_correctly(self):
        """Test that node counting works correctly for deep trees."""
        # Create a tree with 100 nodes (10 branches of 10 nodes each)
        conditions = []
        for i in range(10):
            branch = {
                "type": "LOGICAL",
                "operator": "OR",
                "conditions": [],
            }
            for j in range(9):
                branch["conditions"].append(
                    {
                        "type": "CONDITION",
                        "field": f"field_{i}_{j}",
                        "operator": "EQ",
                        "value": j,
                    }
                )
            # Add one more level
            branch["conditions"].append(
                {
                    "type": "CONDITION",
                    "field": f"field_{i}_9",
                    "operator": "EQ",
                    "value": 9,
                }
            )
            conditions.append(branch)

        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": conditions,
        }

        # Should not raise any exception (111 nodes: 1 root + 10 branches + 100 conditions)
        validate_condition_tree_node_count(condition, max_nodes=1000)

    @pytest.mark.anyio
    async def test_should_reject_tree_exceeding_max_nodes(self):
        """Test that a tree with too many nodes fails validation."""
        # Create a tree with 1001 nodes (exceeds default max of 1000)
        conditions = []
        for i in range(1000):
            conditions.append(
                {
                    "type": "CONDITION",
                    "field": f"field_{i}",
                    "operator": "EQ",
                    "value": i,
                }
            )

        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": conditions,
        }

        # Should raise ValueError (1001 nodes exceeds 1000)
        with pytest.raises(ValueError, match="Condition tree exceeds maximum node count of 1000"):
            validate_condition_tree_node_count(condition, max_nodes=1000)

    @pytest.mark.anyio
    async def test_should_accept_tree_at_exactly_max_nodes(self):
        """Test that a tree with exactly max_nodes passes validation."""
        # Create a tree with exactly 100 nodes
        conditions = []
        for i in range(99):
            conditions.append(
                {
                    "type": "CONDITION",
                    "field": f"field_{i}",
                    "operator": "EQ",
                    "value": i,
                }
            )

        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": conditions,
        }

        # Should not raise any exception (100 nodes == max_nodes=100)
        validate_condition_tree_node_count(condition, max_nodes=100)

    @pytest.mark.anyio
    async def test_should_respect_custom_max_nodes(self):
        """Test that custom max_nodes parameter is respected."""
        # Create a tree with 50 nodes
        conditions = []
        for i in range(49):
            conditions.append(
                {
                    "type": "CONDITION",
                    "field": f"field_{i}",
                    "operator": "EQ",
                    "value": i,
                }
            )

        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": conditions,
        }

        # Should pass with max_nodes=100
        validate_condition_tree_node_count(condition, max_nodes=100)

        # Should fail with max_nodes=10
        with pytest.raises(ValueError, match="Condition tree exceeds maximum node count of 10"):
            validate_condition_tree_node_count(condition, max_nodes=10)

    @pytest.mark.anyio
    async def test_should_count_complex_nested_tree(self):
        """Test node counting for a complex nested tree structure."""
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {
                    "type": "LOGICAL",
                    "operator": "OR",
                    "conditions": [
                        {
                            "type": "CONDITION",
                            "field": "amount",
                            "operator": "GT",
                            "value": 100,
                        },
                        {
                            "type": "CONDITION",
                            "field": "amount",
                            "operator": "LT",
                            "value": 1000,
                        },
                    ],
                },
                {
                    "type": "LOGICAL",
                    "operator": "NOT",
                    "conditions": [
                        {
                            "type": "CONDITION",
                            "field": "country",
                            "operator": "EQ",
                            "value": "XX",
                        }
                    ],
                },
                {
                    "type": "CONDITION",
                    "field": "currency",
                    "operator": "EQ",
                    "value": "USD",
                },
            ],
        }

        # Count: 1 root + 2 logical children + 4 conditions = 7 nodes
        validate_condition_tree_node_count(condition, max_nodes=10)

        # Should fail with max_nodes=5
        with pytest.raises(ValueError, match="Condition tree exceeds maximum node count of 5"):
            validate_condition_tree_node_count(condition, max_nodes=5)

    @pytest.mark.anyio
    async def test_should_include_error_message_with_actual_count(self):
        """Test that error message includes actual node count."""
        # Create a tree with 105 nodes
        conditions = []
        for i in range(104):
            conditions.append(
                {
                    "type": "CONDITION",
                    "field": f"field_{i}",
                    "operator": "EQ",
                    "value": i,
                }
            )

        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": conditions,
        }

        # Should raise ValueError with specific count in message
        with pytest.raises(ValueError, match=r"got 105 nodes"):
            validate_condition_tree_node_count(condition, max_nodes=100)

    @pytest.mark.anyio
    async def test_should_handle_mixed_depth_and_width(self):
        """Test node counting for trees with varying depth and width."""
        # Create a tree that's wide but shallow
        wide_conditions = []
        for i in range(50):
            wide_conditions.append(
                {
                    "type": "CONDITION",
                    "field": f"wide_{i}",
                    "operator": "EQ",
                    "value": i,
                }
            )

        # Create a tree that's narrow but deep
        deep_condition = {"type": "CONDITION", "field": "deep_0", "operator": "EQ", "value": 0}
        for _i in range(1, 50):
            deep_condition = {
                "type": "LOGICAL",
                "operator": "AND",
                "conditions": [deep_condition],
            }

        # Combine both
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {"type": "LOGICAL", "operator": "AND", "conditions": wide_conditions},
                deep_condition,
            ],
        }

        # Total: 1 root + (1 logical + 50 wide leaves) + (49 logical + 1 deep leaf) = 102 nodes
        with pytest.raises(ValueError, match=r"got 102 nodes"):
            validate_condition_tree_node_count(condition, max_nodes=100)

        # Should pass with max_nodes=150
        validate_condition_tree_node_count(condition, max_nodes=150)


class TestValidateConditionTreeDepthEdgeCases:
    """Additional edge case tests for validate_condition_tree_depth."""

    @pytest.mark.anyio
    async def test_should_handle_condition_without_type(self):
        """Test that a condition node without type field is handled."""
        # A node without type should not recurse into children
        condition = {
            "field": "amount",
            "operator": "GT",
            "value": 100,
        }

        # Should not raise any exception
        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_handle_or_type_with_nested_conditions(self):
        """Test depth validation with OR type format."""
        condition = {
            "type": "OR",
            "conditions": [
                {
                    "type": "OR",
                    "conditions": [
                        {
                            "type": "CONDITION",
                            "field": "amount",
                            "operator": "GT",
                            "value": 100,
                        }
                    ],
                }
            ],
        }

        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_handle_not_type_with_nested_conditions(self):
        """Test depth validation with NOT type format."""
        condition = {
            "type": "NOT",
            "conditions": [
                {
                    "type": "NOT",
                    "conditions": [
                        {
                            "type": "CONDITION",
                            "field": "country",
                            "operator": "EQ",
                            "value": "XX",
                        }
                    ],
                }
            ],
        }

        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_handle_mixed_logical_types(self):
        """Test depth validation with mixed LOGICAL/AND/OR/NOT types."""
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {
                    "type": "OR",
                    "conditions": [
                        {
                            "type": "NOT",
                            "conditions": [
                                {
                                    "type": "LOGICAL",
                                    "operator": "AND",
                                    "conditions": [
                                        {
                                            "type": "CONDITION",
                                            "field": "amount",
                                            "operator": "GT",
                                            "value": 100,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        validate_condition_tree_depth(condition, max_depth=10)

    @pytest.mark.anyio
    async def test_should_handle_zero_max_depth(self):
        """Test that max_depth=0 allows only root level."""
        condition = {
            "type": "CONDITION",
            "field": "amount",
            "operator": "GT",
            "value": 100,
        }

        # Should pass - root node is at depth 0
        validate_condition_tree_depth(condition, max_depth=0)

    @pytest.mark.anyio
    async def test_should_handle_BLOCKLIST_current_depth(self):
        """Test that BLOCKLIST current_depth is handled (edge case)."""
        condition = {
            "type": "CONDITION",
            "field": "amount",
            "operator": "GT",
            "value": 100,
        }

        # Should not raise - depth -1 is still <= max_depth
        validate_condition_tree_depth(condition, max_depth=10, current_depth=-1)


class TestValidateConditionTreeNodeCountEdgeCases:
    """Additional edge case tests for validate_condition_tree_node_count."""

    @pytest.mark.anyio
    async def test_should_count_and_type_nodes(self):
        """Test that AND type nodes are counted correctly."""
        condition = {
            "type": "AND",
            "conditions": [
                {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
                {"type": "CONDITION", "field": "country", "operator": "EQ", "value": "US"},
            ],
        }

        # Should count: 1 AND node + 2 condition nodes = 3 nodes
        validate_condition_tree_node_count(condition, max_nodes=10)

    @pytest.mark.anyio
    async def test_should_count_or_type_nodes(self):
        """Test that OR type nodes are counted correctly."""
        condition = {
            "type": "OR",
            "conditions": [
                {"type": "CONDITION", "field": "amount", "operator": "GT", "value": 100},
                {"type": "CONDITION", "field": "amount", "operator": "LT", "value": 1000},
            ],
        }

        # Should count: 1 OR node + 2 condition nodes = 3 nodes
        validate_condition_tree_node_count(condition, max_nodes=10)

    @pytest.mark.anyio
    async def test_should_count_not_type_nodes(self):
        """Test that NOT type nodes are counted correctly."""
        condition = {
            "type": "NOT",
            "conditions": [
                {"type": "CONDITION", "field": "country", "operator": "EQ", "value": "XX"}
            ],
        }

        # Should count: 1 NOT node + 1 condition node = 2 nodes
        validate_condition_tree_node_count(condition, max_nodes=10)

    @pytest.mark.anyio
    async def test_should_count_mixed_type_nodes(self):
        """Test node counting with mixed LOGICAL/AND/OR/NOT types."""
        condition = {
            "type": "LOGICAL",
            "operator": "AND",
            "conditions": [
                {
                    "type": "OR",
                    "conditions": [
                        {
                            "type": "NOT",
                            "conditions": [
                                {
                                    "type": "AND",
                                    "conditions": [
                                        {
                                            "type": "CONDITION",
                                            "field": "amount",
                                            "operator": "GT",
                                            "value": 100,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        # Should count: 1 LOGICAL + 1 OR + 1 NOT + 1 AND + 1 CONDITION = 5 nodes
        validate_condition_tree_node_count(condition, max_nodes=10)

    @pytest.mark.anyio
    async def test_should_handle_node_without_type(self):
        """Test that a node without type field is counted as single node."""
        condition = {
            "field": "amount",
            "operator": "GT",
            "value": 100,
        }

        # Should count as 1 node (no children to recurse into)
        validate_condition_tree_node_count(condition, max_nodes=10)

    @pytest.mark.anyio
    async def test_should_handle_complex_mixed_tree(self):
        """Test node counting for a complex tree with all types."""
        condition = {
            "type": "AND",
            "conditions": [
                {
                    "type": "LOGICAL",
                    "operator": "OR",
                    "conditions": [
                        {"type": "CONDITION", "field": "a", "operator": "EQ", "value": 1},
                        {
                            "type": "NOT",
                            "conditions": [
                                {"type": "CONDITION", "field": "b", "operator": "EQ", "value": 2}
                            ],
                        },
                    ],
                },
                {"type": "CONDITION", "field": "c", "operator": "EQ", "value": 3},
            ],
        }

        # Count: 1 AND + 1 LOGICAL + 2 CONDITIONS + 1 NOT + 1 CONDITION + 1 CONDITION = 7 nodes
        validate_condition_tree_node_count(condition, max_nodes=10)

        # Should fail with max_nodes=5
        with pytest.raises(ValueError, match="Condition tree exceeds maximum node count of 5"):
            validate_condition_tree_node_count(condition, max_nodes=5)


class TestValidateUUIDString:
    """Tests for validate_uuid_string function in app.db.validators.

    This validator is used with SQLAlchemy's @validates decorator
    to ensure UUID fields are consistently stored as valid UUID strings.
    """

    @pytest.mark.anyio
    async def test_valid_uuid_string_accepted(self):
        """Test that valid UUID string format is accepted."""
        uuid_value = "01912345-1234-1234-1234-123456789abc"
        result = validate_uuid_string("test_field", uuid_value)
        assert result == uuid_value

    @pytest.mark.anyio
    async def test_valid_uuid7_object_accepted(self):
        """Test that UUID7 object is converted to string."""
        uuid7_value = uuid.uuid7()
        result = validate_uuid_string("test_field", uuid7_value)
        assert result == str(uuid7_value)
        assert uuid7_value.version == 7

    @pytest.mark.anyio
    async def test_valid_uuid4_object_accepted(self):
        """Test that UUID4 object is converted to string."""
        uuid4_value = uuid.uuid4()
        result = validate_uuid_string("test_field", uuid4_value)
        assert result == str(uuid4_value)

    @pytest.mark.anyio
    async def test_valid_uuid_string_lowercase_accepted(self):
        """Test that lowercase UUID string is accepted."""
        uuid_value = "01912345-1234-1234-1234-123456789abc"
        result = validate_uuid_string("test_field", uuid_value.lower())
        assert result == uuid_value.lower()

    @pytest.mark.anyio
    async def test_valid_uuid_string_uppercase_accepted(self):
        """Test that uppercase UUID string is accepted."""
        uuid_value = "01912345-1234-1234-1234-123456789ABC"
        result = validate_uuid_string("test_field", uuid_value)
        assert result == uuid_value

    @pytest.mark.anyio
    async def test_invalid_uuid_string_too_short(self):
        """Test that UUID string too short is rejected."""
        with pytest.raises(ValueError, match="Invalid UUID format"):
            validate_uuid_string("test_field", "01912345-1234")

    @pytest.mark.anyio
    async def test_invalid_uuid_string_too_long(self):
        """Test that UUID string with extra characters is rejected."""
        with pytest.raises(ValueError, match="Invalid UUID format"):
            validate_uuid_string("test_field", "01912345-1234-1234-1234-123456789abc-extra")

    @pytest.mark.anyio
    async def test_invalid_uuid_string_missing_hyphens(self):
        """Test that UUID string without hyphens is accepted (Python's UUID parser accepts it)."""
        uuid_value = "01912345123412341234123456789abc"
        result = validate_uuid_string("test_field", uuid_value)
        assert result == uuid_value

    @pytest.mark.anyio
    async def test_invalid_uuid_string_not_string(self):
        """Test that non-string UUID is rejected."""
        with pytest.raises(ValueError, match="Expected UUID or str"):
            validate_uuid_string("test_field", 12345)

    @pytest.mark.anyio
    async def test_invalid_uuid_string_none(self):
        """Test that None UUID is rejected."""
        with pytest.raises(ValueError, match="Expected UUID or str"):
            validate_uuid_string("test_field", None)

    @pytest.mark.anyio
    async def test_invalid_uuid_string_empty(self):
        """Test that empty string UUID is rejected."""
        with pytest.raises(ValueError, match="Invalid UUID format"):
            validate_uuid_string("test_field", "")

    @pytest.mark.anyio
    async def test_invalid_uuid_string_special_chars(self):
        """Test that UUID string with special characters is rejected."""
        with pytest.raises(ValueError, match="Invalid UUID format"):
            validate_uuid_string("test_field", "01912345-1234-1234-1234-123456789ab@")

    @pytest.mark.anyio
    async def test_invalid_uuid_string_integer(self):
        """Test that integer UUID is rejected."""
        with pytest.raises(ValueError, match="Expected UUID or str"):
            validate_uuid_string("test_field", 12345)

    @pytest.mark.anyio
    async def test_invalid_uuid_string_float(self):
        """Test that float UUID is rejected."""
        with pytest.raises(ValueError, match="Expected UUID or str"):
            validate_uuid_string("test_field", 12345.67)

    @pytest.mark.anyio
    async def test_invalid_uuid_string_list(self):
        """Test that list UUID is rejected."""
        with pytest.raises(ValueError, match="Expected UUID or str"):
            validate_uuid_string("test_field", ["01912345-1234-1234-1234-123456789abc"])

    @pytest.mark.anyio
    async def test_valid_uuid7_string_from_uuid7_object(self):
        """Test that UUID7 object produces valid UUID7 string."""
        uuid7_value = uuid.uuid7()
        result = validate_uuid_string("test_field", uuid7_value)
        parsed = uuid.UUID(result)
        assert parsed.version == 7

    @pytest.mark.anyio
    async def test_key_parameter_not_used_in_output(self):
        """Test that _key parameter doesn't affect the output."""
        uuid_value = "01912345-1234-1234-1234-123456789abc"
        result = validate_uuid_string("any_field_name", uuid_value)
        assert result == uuid_value
