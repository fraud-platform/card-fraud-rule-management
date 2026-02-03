"""
JSON Canonicalization for deterministic AST output.

Ensures that the compiled AST is byte-for-byte identical for the same inputs
by enforcing consistent ordering and structure.

This is CRITICAL for:
- Deployment verification (hash-based diff detection)
- Audit trails (detecting actual semantic changes)
- Cache invalidation (content-based keys)
"""

import json
from typing import Any


def canonicalize_json(obj: Any) -> dict | list | Any:
    """
    Produce a deterministic, canonical representation of a JSON object.

    This function ensures:
    - All dictionary keys are sorted alphabetically
    - Nested structures are recursively canonicalized
    - Consistent representation across Python runs

    Args:
        obj: Python object (dict, list, or primitive) to canonicalize

    Returns:
        Canonicalized version with sorted keys at all levels

    Example:
        >>> original = {"z": 1, "a": {"c": 2, "b": 3}}
        >>> canonical = canonicalize_json(original)
        >>> # Result: {"a": {"b": 3, "c": 2}, "z": 1}
        >>> json.dumps(canonical, sort_keys=True)  # Deterministic JSON string

    Note:
        This does NOT guarantee array order stability. Arrays preserve
        their input order. For rules, we sort by (priority DESC, rule_id ASC)
        in the compiler before canonicalization.
    """
    if isinstance(obj, dict):
        # Sort keys alphabetically and recursively canonicalize values
        return {k: canonicalize_json(v) for k, v in sorted(obj.items())}

    elif isinstance(obj, list):
        # Preserve list order but canonicalize each element
        return [canonicalize_json(item) for item in obj]

    else:
        # Primitives (str, int, float, bool, None) pass through unchanged
        return obj


def to_canonical_json_string(obj: Any) -> str:
    """
    Convert a Python object to a canonical JSON string.

    This combines canonicalization with deterministic serialization.
    Useful for generating hashes, storing in database, or comparing outputs.

    Args:
        obj: Python object to serialize

    Returns:
        Canonical JSON string with sorted keys and no extra whitespace

    Example:
        >>> data = {"rulesetId": "rs-123", "version": 7}
        >>> to_canonical_json_string(data)
        '{"rulesetId":"rs-123","version":7}'
    """
    canonical = canonicalize_json(obj)

    # Serialize with sorted keys and no extra whitespace
    # separators=(',', ':') removes spaces after commas and colons
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def to_canonical_json_pretty(obj: Any) -> str:
    """
    Convert a Python object to a pretty-printed canonical JSON string.

    Useful for human-readable output in logs, API responses, or debugging.

    Args:
        obj: Python object to serialize

    Returns:
        Canonical JSON string with sorted keys and indentation

    Example:
        >>> data = {"rulesetId": "rs-123", "version": 7}
        >>> print(to_canonical_json_pretty(data))
        {
          "rulesetId": "rs-123",
          "version": 7
        }
    """
    canonical = canonicalize_json(obj)

    # Serialize with sorted keys and 2-space indentation
    return json.dumps(canonical, sort_keys=True, indent=2, ensure_ascii=False)
