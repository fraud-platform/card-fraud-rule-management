"""Shared validators for Pydantic schemas."""

import re
from typing import Any

from pydantic import field_validator, model_validator

# UUID v7 format pattern (simplified - validates UUID format in general)
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_uuid(value: str, field_name: str = "UUID") -> str:
    """
    Validate that a string is a properly formatted UUID.

    Args:
        value: String to validate
        field_name: Name of the field for error messages

    Returns:
        The validated UUID string

    Raises:
        ValueError: If the value is not a valid UUID format
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    if not UUID_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be a valid UUID format (e.g., '01912345-1234-1234-1234-123456789abc')"
        )

    return value


def validate_condition_tree_depth(
    condition: dict, max_depth: int = 10, current_depth: int = 0
) -> None:
    """
    Validate that condition tree doesn't exceed maximum depth.

    Args:
        condition: Condition tree dictionary
        max_depth: Maximum allowed depth (default: 10)
        current_depth: Current depth in recursion

    Raises:
        ValueError: If tree exceeds maximum depth
    """
    if current_depth > max_depth:
        raise ValueError(f"Condition tree exceeds maximum depth of {max_depth}")

    # Check for logical operators (both formats: "type": "LOGICAL" and "type": "AND"/"OR")
    node_type = condition.get("type", "")
    if node_type in ("LOGICAL", "AND", "OR", "NOT"):
        # Recursively validate nested conditions
        children = condition.get("conditions", [])
        if node_type == "LOGICAL":
            # For "LOGICAL" type format
            children = condition.get("conditions", [])
        else:
            # For "AND"/"OR"/"NOT" type format
            children = condition.get("conditions", [])

        for child in children:
            validate_condition_tree_depth(child, max_depth, current_depth + 1)


def validate_condition_tree_node_count(condition: dict, max_nodes: int = 1000) -> None:
    """
    Validate that condition tree doesn't exceed maximum node count.

    This prevents DoS attacks via excessively large condition trees.
    Counts both logical nodes (and/or/not) and leaf nodes (field predicates).

    Args:
        condition: Condition tree dictionary
        max_nodes: Maximum allowed nodes (default: 1000)

    Raises:
        ValueError: If tree exceeds maximum node count
    """

    def count_nodes(node: dict) -> int:
        """Recursively count all nodes in the condition tree."""
        # Count current node
        count = 1

        # If it's a logical node, count all children
        # Support both "LOGICAL" type and "AND"/"OR"/"NOT" types
        node_type = node.get("type", "")
        if node_type in ("LOGICAL", "AND", "OR", "NOT"):
            for child in node.get("conditions", []):
                count += count_nodes(child)

        return count

    node_count = count_nodes(condition)

    if node_count > max_nodes:
        raise ValueError(
            f"Condition tree exceeds maximum node count of {max_nodes} (got {node_count} nodes)"
        )


class ConditionTreeValidator:
    """Validator class for condition trees."""

    @staticmethod
    @field_validator("*", mode="before")
    @classmethod
    def validate_condition_tree(cls, v: Any) -> dict:
        """
        Validate condition tree structure, depth, and node count.

        Args:
            v: Condition tree value

        Returns:
            Validated condition tree

        Raises:
            ValueError: If tree is invalid, too deep, or has too many nodes
        """
        if not isinstance(v, dict):
            raise ValueError("condition_tree must be a dictionary")

        if not v:
            raise ValueError("condition_tree cannot be empty")

        # Validate depth (supports both LOGICAL and AND/OR/NOT formats)
        try:
            validate_condition_tree_depth(v, max_depth=10)
        except ValueError as e:
            raise ValueError(str(e)) from e

        # Validate node count (supports both LOGICAL and AND/OR/NOT formats)
        try:
            validate_condition_tree_node_count(v, max_nodes=1000)
        except ValueError as e:
            raise ValueError(str(e)) from e

        return v

    @staticmethod
    @model_validator(mode="after")
    def validate_max_array_size(cls, model: Any, max_size: int = 100) -> Any:
        """
        Validate that arrays in condition tree don't exceed maximum size.

        Args:
            model: Pydantic model being validated
            max_size: Maximum array size (default: 100)

        Returns:
            Validated model

        Raises:
            ValueError: If array too large
        """

        def check_arrays(obj: Any, path: str = "") -> None:
            """Recursively check array sizes."""
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, list) and len(value) > max_size:
                        raise ValueError(
                            f"Array at '{path}.{key}' exceeds maximum size of {max_size}"
                        )
                    check_arrays(value, f"{path}.{key}" if path else key)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_arrays(item, f"{path}[{i}]")

        # Check both condition_tree and any nested structures
        for attr_name in ["condition_tree", "conditions"]:
            if hasattr(model, attr_name):
                try:
                    check_arrays(getattr(model, attr_name), attr_name)
                except ValueError as e:
                    raise ValueError(str(e)) from e

        return model
