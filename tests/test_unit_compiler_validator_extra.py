import pytest

from app.compiler.validator import validate_condition_tree
from app.core.errors import ValidationError


@pytest.mark.anyio
async def test_empty_condition_tree_raises():
    with pytest.raises(ValidationError):
        validate_condition_tree({}, {})


@pytest.mark.anyio
async def test_and_non_list_raises():
    with pytest.raises(ValidationError):
        validate_condition_tree({"and": "not-a-list"}, {})


@pytest.mark.anyio
async def test_and_empty_list_raises():
    with pytest.raises(ValidationError):
        validate_condition_tree({"and": []}, {})


@pytest.mark.anyio
async def test_not_non_dict_raises():
    with pytest.raises(ValidationError):
        validate_condition_tree({"not": "string"}, {})


@pytest.mark.anyio
async def test_leaf_missing_components_raises():
    # Missing 'field'
    with pytest.raises(ValidationError):
        validate_condition_tree({"op": "EQ", "value": "x"}, {})

    # Missing 'op'
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "amount", "value": 1}, {})

    # Missing 'value'
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "amount", "op": "EQ"}, {})


@pytest.mark.anyio
async def test_unknown_field_strict_mode_raises():
    fields = {
        "amount": {
            "data_type": "NUMBER",
            "allowed_operators": ["GT"],
            "multi_value_allowed": False,
            "is_active": True,
        }
    }
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "unknown", "op": "EQ", "value": 1}, fields)


@pytest.mark.anyio
async def test_allow_unknown_fields_lenient_mode_passes():
    fields = {}
    # Should not raise when allow_unknown_fields=True
    validate_condition_tree(
        {"field": "unknown", "op": "EQ", "value": 1}, fields, allow_unknown_fields=True
    )


@pytest.mark.anyio
async def test_inactive_field_raises():
    fields = {
        "amount": {
            "data_type": "NUMBER",
            "allowed_operators": ["GT"],
            "multi_value_allowed": False,
            "is_active": False,
        }
    }
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "amount", "op": "GT", "value": 100}, fields)


@pytest.mark.anyio
async def test_operator_not_allowed_raises():
    fields = {
        "mcc": {
            "data_type": "STRING",
            "allowed_operators": ["EQ"],
            "multi_value_allowed": False,
            "is_active": True,
        }
    }
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "mcc", "op": "GT", "value": 5}, fields)


@pytest.mark.anyio
async def test_between_requires_two_values():
    fields = {
        "amount": {
            "data_type": "NUMBER",
            "allowed_operators": ["BETWEEN"],
            "multi_value_allowed": False,
            "is_active": True,
        }
    }
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "amount", "op": "BETWEEN", "value": [1]}, fields)


@pytest.mark.anyio
async def test_in_requires_list():
    fields = {
        "mcc": {
            "data_type": "STRING",
            "allowed_operators": ["IN"],
            "multi_value_allowed": True,
            "is_active": True,
        }
    }
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "mcc", "op": "IN", "value": "not-a-list"}, fields)


@pytest.mark.anyio
async def test_type_mismatch_raises():
    fields = {
        "amount": {
            "data_type": "NUMBER",
            "allowed_operators": ["GT"],
            "multi_value_allowed": False,
            "is_active": True,
        }
    }
    with pytest.raises(ValidationError):
        validate_condition_tree({"field": "amount", "op": "GT", "value": "not-a-number"}, fields)


class TestValidatorEdgeCases:
    """Additional edge case tests for compiler validator."""

    @pytest.mark.anyio
    async def test_or_non_list_raises(self):
        """Test that OR with non-list raises."""
        with pytest.raises(ValidationError):
            validate_condition_tree({"or": "string"}, {})

    @pytest.mark.anyio
    async def test_or_empty_list_raises(self):
        """Test that OR with empty list raises."""
        with pytest.raises(ValidationError):
            validate_condition_tree({"or": []}, {})

    @pytest.mark.anyio
    async def test_not_empty_conditions_raises(self):
        """Test that NOT with conditions raises."""
        with pytest.raises(ValidationError):
            validate_condition_tree({"not": {}}, {})

    @pytest.mark.anyio
    async def test_nested_and_or(self):
        """Test nested AND/OR conditions."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT", "LT"],
                "multi_value_allowed": False,
                "is_active": True,
            },
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            },
        }
        condition = {
            "and": [
                {"field": "amount", "op": "GT", "value": 100},
                {
                    "or": [
                        {"field": "country", "op": "EQ", "value": "US"},
                        {"field": "country", "op": "EQ", "value": "CA"},
                    ]
                },
            ]
        }
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_not_condition(self):
        """Test NOT condition validation."""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"not": {"field": "country", "op": "EQ", "value": "XX"}}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_multi_value_allowed(self):
        """Test multi-value operator validation."""
        fields = {
            "mcc": {
                "data_type": "STRING",
                "allowed_operators": ["IN"],
                "multi_value_allowed": True,
                "is_active": True,
            }
        }
        condition = {"field": "mcc", "op": "IN", "value": ["5411", "5541"]}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_multi_value_not_allowed_raises(self):
        """Test multi-value not allowed raises."""
        fields = {
            "mcc": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError):
            validate_condition_tree({"field": "mcc", "op": "EQ", "value": ["5411"]}, fields)

    @pytest.mark.anyio
    async def test_string_with_number_type(self):
        """Test string value for NUMBER type raises."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError):
            validate_condition_tree(
                {"field": "amount", "op": "EQ", "value": "not-a-number"}, fields
            )

    @pytest.mark.anyio
    async def test_valid_number_condition(self):
        """Test valid NUMBER condition passes."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["EQ", "GT", "LT", "BETWEEN"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "amount", "op": "GT", "value": 100.5}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_valid_string_condition(self):
        """Test valid STRING condition passes."""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN"],
                "multi_value_allowed": True,
                "is_active": True,
            }
        }
        condition = {"field": "country", "op": "EQ", "value": "US"}
        validate_condition_tree(condition, fields)


class TestTypeBasedFormatNodes:
    """Tests for type-based format nodes: {"type": "AND/OR/NOT/CONDITION", ...}"""

    @pytest.mark.anyio
    async def test_type_based_and_node(self):
        """Test type-based AND format: {"type": "AND", "conditions": [...]}"""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {
            "type": "AND",
            "conditions": [
                {"field": "amount", "op": "GT", "value": 100},
                {"field": "amount", "op": "GT", "value": 200},
            ],
        }
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_type_based_and_non_list_raises(self):
        """Test type-based AND with non-list raises."""
        with pytest.raises(ValidationError):
            validate_condition_tree({"type": "AND", "conditions": "not-a-list"}, {})

    @pytest.mark.anyio
    async def test_type_based_and_empty_list_raises(self):
        """Test type-based AND with empty list raises."""
        with pytest.raises(ValidationError):
            validate_condition_tree({"type": "AND", "conditions": []}, {})

    @pytest.mark.anyio
    async def test_type_based_or_node(self):
        """Test type-based OR format: {"type": "OR", "conditions": [...]}"""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {
            "type": "OR",
            "conditions": [
                {"field": "country", "op": "EQ", "value": "US"},
                {"field": "country", "op": "EQ", "value": "CA"},
            ],
        }
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_type_based_not_node(self):
        """Test type-based NOT format: {"type": "NOT", "condition": {...}}"""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {
            "type": "NOT",
            "condition": {"field": "country", "op": "EQ", "value": "XX"},
        }
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_type_based_not_non_dict_raises(self):
        """Test type-based NOT with non-dict raises."""
        with pytest.raises(ValidationError):
            validate_condition_tree({"type": "NOT", "condition": "string"}, {})

    @pytest.mark.anyio
    async def test_type_based_condition_node(self):
        """Test type-based CONDITION format: {"type": "CONDITION", ...}"""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {
            "type": "CONDITION",
            "field": "amount",
            "op": "GT",
            "value": 100,
        }
        validate_condition_tree(condition, fields)


class TestInvalidNodeType:
    """Tests for invalid node types."""

    @pytest.mark.anyio
    async def test_node_not_dict_raises(self):
        """Test that non-dict node raises ValidationError."""
        with pytest.raises(ValidationError, match="must be a dictionary"):
            validate_condition_tree("string", {})

    @pytest.mark.anyio
    async def test_node_list_raises(self):
        """Test that list node raises ValidationError (caught as empty condition tree)."""
        with pytest.raises(ValidationError):
            validate_condition_tree([], {})

    @pytest.mark.anyio
    async def test_node_number_raises(self):
        """Test that number node raises ValidationError (caught as empty condition tree)."""
        with pytest.raises(ValidationError):
            validate_condition_tree(123, {})

    @pytest.mark.anyio
    async def test_node_none_raises(self):
        """Test that None node raises ValidationError."""
        with pytest.raises(ValidationError, match="Condition tree cannot be empty"):
            validate_condition_tree(None, {})


class TestFieldObjectReference:
    """Tests for field as object (velocity fields with field_key)."""

    @pytest.mark.anyio
    async def test_field_as_object_with_field_key(self):
        """Test field as object with field_key property."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {
            "field": {"field_key": "amount"},
            "op": "GT",
            "value": 100,
        }
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_field_as_object_without_field_key_raises(self):
        """Test field as object without field_key raises."""
        with pytest.raises(ValidationError, match="Invalid field reference"):
            validate_condition_tree(
                {"field": {"not_field_key": "amount"}, "op": "GT", "value": 100}, {}
            )

    @pytest.mark.anyio
    async def test_field_as_list_raises(self):
        """Test field as list raises."""
        with pytest.raises(ValidationError, match="Invalid field reference"):
            validate_condition_tree({"field": ["amount"], "op": "GT", "value": 100}, {})


class TestBetweenValidation:
    """Tests for BETWEEN operator validation."""

    @pytest.mark.anyio
    async def test_between_with_single_value_raises(self):
        """Test BETWEEN with single value raises."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["BETWEEN"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="requires exactly 2 values"):
            validate_condition_tree({"field": "amount", "op": "BETWEEN", "value": [100]}, fields)

    @pytest.mark.anyio
    async def test_between_with_three_values_raises(self):
        """Test BETWEEN with three values raises."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["BETWEEN"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="requires exactly 2 values"):
            validate_condition_tree(
                {"field": "amount", "op": "BETWEEN", "value": [10, 100, 200]}, fields
            )

    @pytest.mark.anyio
    async def test_between_with_non_list_raises(self):
        """Test BETWEEN with non-list raises."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["BETWEEN"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="requires exactly 2 values"):
            validate_condition_tree({"field": "amount", "op": "BETWEEN", "value": 100}, fields)

    @pytest.mark.anyio
    async def test_between_with_invalid_type_in_range(self):
        """Test BETWEEN with invalid type in range raises."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["BETWEEN"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="expects NUMBER value"):
            validate_condition_tree(
                {"field": "amount", "op": "BETWEEN", "value": [10, "not-a-number"]}, fields
            )


class TestBooleanValidation:
    """Tests for BOOLEAN type validation."""

    @pytest.mark.anyio
    async def test_boolean_type_with_true(self):
        """Test BOOLEAN type with True value passes."""
        fields = {
            "is_active": {
                "data_type": "BOOLEAN",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "is_active", "op": "EQ", "value": True}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_boolean_type_with_false(self):
        """Test BOOLEAN type with False value passes."""
        fields = {
            "is_active": {
                "data_type": "BOOLEAN",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "is_active", "op": "EQ", "value": False}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_boolean_type_with_string_raises(self):
        """Test BOOLEAN type with string raises."""
        fields = {
            "is_active": {
                "data_type": "BOOLEAN",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="expects BOOLEAN value"):
            validate_condition_tree({"field": "is_active", "op": "EQ", "value": "true"}, fields)

    @pytest.mark.anyio
    async def test_boolean_type_with_number_raises(self):
        """Test BOOLEAN type with number raises."""
        fields = {
            "is_active": {
                "data_type": "BOOLEAN",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="expects BOOLEAN value"):
            validate_condition_tree({"field": "is_active", "op": "EQ", "value": 1}, fields)


class TestDateValidation:
    """Tests for DATE type validation."""

    @pytest.mark.anyio
    async def test_date_type_with_iso8601_string(self):
        """Test DATE type with ISO 8601 string passes."""
        fields = {
            "created_at": {
                "data_type": "DATE",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "created_at", "op": "GT", "value": "2024-01-15T10:30:00Z"}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_date_type_with_date_only_string(self):
        """Test DATE type with date-only string passes."""
        fields = {
            "created_at": {
                "data_type": "DATE",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "created_at", "op": "EQ", "value": "2024-01-15"}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_date_type_with_number_raises(self):
        """Test DATE type with number raises."""
        fields = {
            "created_at": {
                "data_type": "DATE",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="expects DATE string"):
            validate_condition_tree({"field": "created_at", "op": "GT", "value": 12345}, fields)


class TestDataTypeNotString:
    """Tests for data_type not being a string."""

    @pytest.mark.anyio
    async def test_data_type_none_raises(self):
        """Test data_type as None raises."""
        fields = {
            "amount": {
                "data_type": None,
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="missing 'data_type'"):
            validate_condition_tree({"field": "amount", "op": "GT", "value": 100}, fields)

    @pytest.mark.anyio
    async def test_data_type_number_raises(self):
        """Test data_type as number raises."""
        fields = {
            "amount": {
                "data_type": 123,
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="missing 'data_type'"):
            validate_condition_tree({"field": "amount", "op": "GT", "value": 100}, fields)


class TestFieldRefMissing:
    """Tests for field_ref being None or missing."""

    @pytest.mark.anyio
    async def test_field_ref_none_raises(self):
        """Test field_ref as None raises."""
        with pytest.raises(ValidationError, match="missing 'field'"):
            validate_condition_tree({"field": None, "op": "EQ", "value": 1}, {})

    @pytest.mark.anyio
    async def test_field_ref_empty_string_raises(self):
        """Test field_ref as empty string - empty string is treated as missing."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="missing 'field'"):
            validate_condition_tree({"field": "", "op": "EQ", "value": 1}, fields)


class TestNoneValueAllowed:
    """Tests for None/null values."""

    @pytest.mark.anyio
    async def test_none_value_for_string_field(self):
        """Test None value is allowed for any field."""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["EQ"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "country", "op": "EQ", "value": None}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_none_value_for_number_field(self):
        """Test None value is allowed for NUMBER field."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "amount", "op": "GT", "value": None}
        validate_condition_tree(condition, fields)


class TestNotInOperator:
    """Tests for NOT_IN operator."""

    @pytest.mark.anyio
    async def test_not_in_with_list(self):
        """Test NOT_IN with list passes."""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["NOT_IN"],
                "multi_value_allowed": True,
                "is_active": True,
            }
        }
        condition = {"field": "country", "op": "NOT_IN", "value": ["XX", "YY"]}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_not_in_with_non_list_raises(self):
        """Test NOT_IN with non-list raises."""
        fields = {
            "country": {
                "data_type": "STRING",
                "allowed_operators": ["NOT_IN"],
                "multi_value_allowed": True,
                "is_active": True,
            }
        }
        with pytest.raises(ValidationError, match="requires a list"):
            validate_condition_tree({"field": "country", "op": "NOT_IN", "value": "XX"}, fields)


class TestLegacyOperatorKey:
    """Tests for legacy 'operator' key support."""

    @pytest.mark.anyio
    async def test_legacy_operator_key(self):
        """Test that legacy 'operator' key is accepted."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "amount", "operator": "GT", "value": 100}
        validate_condition_tree(condition, fields)

    @pytest.mark.anyio
    async def test_op_takes_precedence_over_operator(self):
        """Test that 'op' key takes precedence over 'operator'."""
        fields = {
            "amount": {
                "data_type": "NUMBER",
                "allowed_operators": ["GT"],
                "multi_value_allowed": False,
                "is_active": True,
            }
        }
        condition = {"field": "amount", "op": "GT", "operator": "LT", "value": 100}
        validate_condition_tree(condition, fields)
