"""
Condition Tree Validation for Fraud Rules.

Validates that condition trees are structurally correct and semantically valid:
- All referenced fields exist and are active
- All operators are allowed for their fields
- All value types match field data types
- Multi-value constraints are respected

This validation is the gatekeeper that prevents invalid rules from being compiled.
"""

import logging
from typing import Any

from app.core.errors import ValidationError
from app.domain.enums import DataType, Operator

logger = logging.getLogger(__name__)


def validate_condition_tree(
    condition_tree: dict, rule_fields: dict[str, dict], allow_unknown_fields: bool = False
) -> None:
    """
    Validate a condition tree against the rule field catalog.

    This is the main entry point for condition tree validation. It performs
    comprehensive checks on structure, field references, operators, and values.

    Args:
        condition_tree: The condition tree to validate (JSONB from database)
        rule_fields: Dictionary mapping field_key -> field metadata
                     Format: {
                         "field_key": {
                             "data_type": "STRING",
                             "allowed_operators": ["EQ", "IN"],
                             "multi_value_allowed": True,
                             "is_active": True
                         }
                     }
        allow_unknown_fields: If True, skip strict validation for fields that are not present
                              in the `rule_fields` catalog (lenient mode used by full compilation).

    Raises:
        ValidationError: If any validation check fails, with detailed context

    Example:
        >>> fields = {
        ...     "mcc": {
        ...         "data_type": "STRING",
        ...         "allowed_operators": ["EQ", "IN"],
        ...         "multi_value_allowed": True,
        ...         "is_active": True
        ...     }
        ... }
        >>> tree = {"field": "mcc", "op": "IN", "value": ["5967"]}
        >>> validate_condition_tree(tree, fields)  # Passes
        >>> bad_tree = {"field": "mcc", "op": "GT", "value": 5}
        >>> validate_condition_tree(bad_tree, fields)  # Raises ValidationError
    """
    if not condition_tree:
        raise ValidationError(
            "Condition tree cannot be empty", details={"condition_tree": condition_tree}
        )

    _validate_node(condition_tree, rule_fields, path="$", allow_unknown_fields=allow_unknown_fields)


def _validate_node(
    node: Any, rule_fields: dict[str, dict], path: str, allow_unknown_fields: bool = False
) -> None:
    """
    Recursively validate a condition tree node.

    Args:
        node: Current node being validated (dict, list, or primitive)
        rule_fields: Field metadata dictionary
        path: JSONPath to current node (for error reporting)

    Raises:
        ValidationError: If validation fails at this node
    """
    if not isinstance(node, dict):
        raise ValidationError(
            f"Condition node must be a dictionary at {path}",
            details={"path": path, "type": type(node).__name__},
        )

    # Check for type-based format first ({"type": "AND/OR/NOT/CONDITION", ...})
    node_type = node.get("type", "").upper() if isinstance(node.get("type"), str) else ""

    # Boolean composition nodes: and, or, not
    # Support both formats: {"and": [...]} and {"type": "AND", "conditions": [...]}
    if "and" in node:
        _validate_boolean_node(node, "and", rule_fields, path, allow_unknown_fields)
    elif "or" in node:
        _validate_boolean_node(node, "or", rule_fields, path, allow_unknown_fields)
    elif "not" in node:
        _validate_not_node(node, rule_fields, path, allow_unknown_fields)
    elif node_type == "AND":
        _validate_type_based_boolean_node(node, "and", rule_fields, path, allow_unknown_fields)
    elif node_type == "OR":
        _validate_type_based_boolean_node(node, "or", rule_fields, path, allow_unknown_fields)
    elif node_type == "NOT":
        _validate_type_based_not_node(node, rule_fields, path, allow_unknown_fields)
    elif "field" in node or node_type == "CONDITION":
        # Leaf predicate node
        _validate_leaf_node(node, rule_fields, path, allow_unknown_fields)
    else:
        raise ValidationError(
            f"Invalid condition node at {path}: must contain 'and', 'or', "
            "'not', 'field', or 'type'",
            details={"path": path, "keys": list(node.keys())},
        )


def _validate_boolean_node(
    node: dict,
    operator: str,
    rule_fields: dict[str, dict],
    path: str,
    allow_unknown_fields: bool = False,
) -> None:
    """
    Validate an 'and' or 'or' boolean composition node.

    Args:
        node: Node containing 'and' or 'or' key
        operator: Either "and" or "or"
        rule_fields: Field metadata dictionary
        path: JSONPath to current node

    Raises:
        ValidationError: If structure or children are invalid
    """
    children = node.get(operator)

    if not isinstance(children, list):
        raise ValidationError(
            f"'{operator}' must be a list at {path}",
            details={"path": path, "type": type(children).__name__},
        )

    if len(children) == 0:
        raise ValidationError(f"'{operator}' cannot be empty at {path}", details={"path": path})

    # Recursively validate each child
    for i, child in enumerate(children):
        child_path = f"{path}.{operator}[{i}]"
        _validate_node(child, rule_fields, child_path, allow_unknown_fields)


def _validate_not_node(
    node: dict, rule_fields: dict[str, dict], path: str, allow_unknown_fields: bool = False
) -> None:
    """
    Validate a 'not' negation node.

    Args:
        node: Node containing 'not' key
        rule_fields: Field metadata dictionary
        path: JSONPath to current node

    Raises:
        ValidationError: If structure or child is invalid
    """
    child = node.get("not")

    if not isinstance(child, dict):
        raise ValidationError(
            f"'not' must contain a single condition object at {path}",
            details={"path": path, "type": type(child).__name__},
        )

    # Recursively validate the child
    child_path = f"{path}.not"
    _validate_node(child, rule_fields, child_path, allow_unknown_fields)


def _validate_type_based_boolean_node(
    node: dict,
    operator: str,
    rule_fields: dict[str, dict],
    path: str,
    allow_unknown_fields: bool = False,
) -> None:
    """
    Validate a type-based 'AND' or 'OR' boolean composition node.

    Format: {"type": "AND"|"OR", "conditions": [...]}

    Args:
        node: Node containing 'type' and 'conditions' keys
        operator: Either "and" or "or"
        rule_fields: Field metadata dictionary
        path: JSONPath to current node

    Raises:
        ValidationError: If structure or children are invalid
    """
    children = node.get("conditions")

    if not isinstance(children, list):
        raise ValidationError(
            f"'conditions' must be a list at {path}",
            details={"path": path, "type": type(children).__name__},
        )

    if len(children) == 0:
        raise ValidationError(f"'conditions' cannot be empty at {path}", details={"path": path})

    # Recursively validate each child
    for i, child in enumerate(children):
        child_path = f"{path}.conditions[{i}]"
        _validate_node(child, rule_fields, child_path, allow_unknown_fields)


def _validate_type_based_not_node(
    node: dict, rule_fields: dict[str, dict], path: str, allow_unknown_fields: bool = False
) -> None:
    """
    Validate a type-based 'NOT' negation node.

    Format: {"type": "NOT", "condition": {...}}

    Args:
        node: Node containing 'type': 'NOT' and 'condition' key
        rule_fields: Field metadata dictionary
        path: JSONPath to current node

    Raises:
        ValidationError: If structure or child is invalid
    """
    child = node.get("condition")

    if not isinstance(child, dict):
        raise ValidationError(
            f"'condition' must contain a single condition object at {path}",
            details={"path": path, "type": type(child).__name__},
        )

    # Recursively validate the child
    child_path = f"{path}.condition"
    _validate_node(child, rule_fields, child_path, allow_unknown_fields)


def _validate_leaf_node(
    node: dict, rule_fields: dict[str, dict], path: str, allow_unknown_fields: bool = False
) -> None:
    """
    Validate a leaf predicate node (field comparison).

    Checks:
    1. Field exists in catalog
    2. Field is active
    3. Operator is allowed for this field
    4. Value type matches field data type
    5. Multi-value constraints are respected

    Args:
        node: Leaf node with "field", "op", and "value"
        rule_fields: Field metadata dictionary
        path: JSONPath to current node

    Raises:
        ValidationError: If any check fails
    """
    # Extract required components
    field_ref = node.get("field")
    # Accept either 'op' or the legacy 'operator' key from API payloads
    operator = node.get("op") or node.get("operator")
    value = node.get("value")

    if not field_ref:
        raise ValidationError(
            f"Leaf node missing 'field' at {path}", details={"path": path, "node": node}
        )

    if not operator:
        raise ValidationError(
            f"Leaf node missing 'op' or 'operator' at {path}", details={"path": path, "node": node}
        )

    if "value" not in node:  # Allow None/null values
        raise ValidationError(
            f"Leaf node missing 'value' at {path}", details={"path": path, "node": node}
        )

    # Support both string field_key and object field structure
    # (for velocity fields, field might be an object)
    if isinstance(field_ref, str):
        field_key = field_ref
    elif isinstance(field_ref, dict) and "field_key" in field_ref:
        field_key = field_ref["field_key"]
    else:
        raise ValidationError(
            f"Invalid field reference at {path}: must be string or object with 'field_key'",
            details={"path": path, "field": field_ref},
        )

    # Check 1: Field exists
    if field_key not in rule_fields:
        if allow_unknown_fields:
            # In lenient mode (used by full compilation), skip strict validation
            logger.warning("Unknown field '%s' at %s - skipping strict validation", field_key, path)
            return
        # In strict mode (unit validation), raise error
        raise ValidationError(
            f"Unknown field '{field_key}' at {path}", details={"path": path, "field_key": field_key}
        )

    field_meta = rule_fields[field_key]

    # Check 2: Field is active
    if not field_meta.get("is_active", True):
        raise ValidationError(
            f"Field '{field_key}' is not active at {path}",
            details={"path": path, "field_key": field_key},
        )

    # Check 3: Operator is allowed
    allowed_operators = field_meta.get("allowed_operators", [])
    if operator not in allowed_operators:
        raise ValidationError(
            f"Operator '{operator}' not allowed for field '{field_key}' at {path}",
            details={
                "path": path,
                "field_key": field_key,
                "operator": operator,
                "allowed_operators": allowed_operators,
            },
        )

    # Check 4: Validate value type
    data_type = field_meta.get("data_type")
    if not isinstance(data_type, str):
        raise ValidationError(
            f"Field '{field_key}' missing 'data_type' at {path}",
            details={"path": path, "field_key": field_key},
        )
    _validate_value_type(field_key, data_type, operator, value, path)

    # Check 5: Multi-value constraints
    multi_value_allowed = field_meta.get("multi_value_allowed", False)
    _validate_multi_value(field_key, operator, multi_value_allowed, path)


def _validate_value_type(
    field_key: str, data_type: str, operator: str, value: Any, path: str
) -> None:
    """
    Validate that value type matches field data type.

    Args:
        field_key: Field identifier (for error messages)
        data_type: Expected data type (STRING, NUMBER, BOOLEAN, DATE, ENUM)
        operator: Operator being used
        value: Value to validate
        path: JSONPath (for error messages)

    Raises:
        ValidationError: If type doesn't match
    """
    # Operators that require lists
    list_operators = {Operator.IN.value, Operator.NOT_IN.value}
    # Operators that require two values (range)
    range_operators = {Operator.BETWEEN.value}

    # BETWEEN requires a list of exactly 2 values
    if operator in range_operators:
        if not isinstance(value, list) or len(value) != 2:
            raise ValidationError(
                f"Operator '{operator}' requires exactly 2 values for "
                f"field '{field_key}' at {path}",
                details={
                    "path": path,
                    "field_key": field_key,
                    "operator": operator,
                    "value": value,
                },
            )
        # Validate each value in the range
        for v in value:
            _check_primitive_type(field_key, data_type, v, path)
        return

    # IN/NOT_IN require lists
    if operator in list_operators:
        if not isinstance(value, list):
            raise ValidationError(
                f"Operator '{operator}' requires a list for field '{field_key}' at {path}",
                details={
                    "path": path,
                    "field_key": field_key,
                    "operator": operator,
                    "value": value,
                },
            )
        # Validate each value in the list
        for v in value:
            _check_primitive_type(field_key, data_type, v, path)
        return

    # Other operators expect single values
    if isinstance(value, list):
        raise ValidationError(
            f"Operator '{operator}' does not accept lists for field '{field_key}' at {path}",
            details={"path": path, "field_key": field_key, "operator": operator, "value": value},
        )

    _check_primitive_type(field_key, data_type, value, path)


def _check_primitive_type(field_key: str, data_type: str, value: Any, path: str) -> None:
    """
    Check that a primitive value matches the expected data type.

    Args:
        field_key: Field identifier
        data_type: Expected type
        value: Primitive value to check
        path: JSONPath

    Raises:
        ValidationError: If type doesn't match
    """
    if value is None:
        # Allow None for nullable comparisons
        return

    if data_type == DataType.STRING.value or data_type == DataType.ENUM.value:
        if not isinstance(value, str):
            raise ValidationError(
                f"Field '{field_key}' expects STRING/ENUM value at {path}",
                details={
                    "path": path,
                    "field_key": field_key,
                    "expected_type": data_type,
                    "actual_type": type(value).__name__,
                    "value": value,
                },
            )

    elif data_type == DataType.NUMBER.value:
        if not isinstance(value, (int, float)):
            raise ValidationError(
                f"Field '{field_key}' expects NUMBER value at {path}",
                details={
                    "path": path,
                    "field_key": field_key,
                    "expected_type": data_type,
                    "actual_type": type(value).__name__,
                    "value": value,
                },
            )

    elif data_type == DataType.BOOLEAN.value:
        if not isinstance(value, bool):
            raise ValidationError(
                f"Field '{field_key}' expects BOOLEAN value at {path}",
                details={
                    "path": path,
                    "field_key": field_key,
                    "expected_type": data_type,
                    "actual_type": type(value).__name__,
                    "value": value,
                },
            )

    elif data_type == DataType.DATE.value:
        # Accept string representation of dates (ISO 8601)
        if not isinstance(value, str):
            raise ValidationError(
                f"Field '{field_key}' expects DATE string (ISO 8601) at {path}",
                details={
                    "path": path,
                    "field_key": field_key,
                    "expected_type": data_type,
                    "actual_type": type(value).__name__,
                    "value": value,
                },
            )
        # Could add ISO 8601 format validation here if needed


def _validate_multi_value(
    field_key: str, operator: str, multi_value_allowed: bool, path: str
) -> None:
    """
    Validate multi-value constraints.

    If field does not allow multi-value, IN/NOT_IN operators should be rejected.

    Args:
        field_key: Field identifier
        operator: Operator being used
        value: Value (may be list)
        multi_value_allowed: Whether field allows multi-value
        path: JSONPath

    Raises:
        ValidationError: If multi-value constraint violated
    """
    list_operators = {Operator.IN.value, Operator.NOT_IN.value}

    if operator in list_operators and not multi_value_allowed:
        raise ValidationError(
            f"Field '{field_key}' does not allow multi-value operators (IN/NOT_IN) at {path}",
            details={
                "path": path,
                "field_key": field_key,
                "operator": operator,
                "multi_value_allowed": multi_value_allowed,
            },
        )
