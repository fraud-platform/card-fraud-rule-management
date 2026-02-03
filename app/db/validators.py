"""Reusable SQLAlchemy validators for the Fraud Governance API."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

JsonType = dict[str, "JsonType"] | list["JsonType"] | str | int | float | bool | None


def validate_uuid_string(_key: str, value: uuid.UUID | str) -> str:
    """Convert UUID to string and validate format.

    This validator can be used with SQLAlchemy's @validates decorator
    to ensure UUID fields are consistently stored as valid UUID strings.

    Args:
        _key: The field name being validated (unused, required by SQLAlchemy)
        value: UUID object or string representation

    Returns:
        String representation of the UUID

    Raises:
        ValueError: If the value is not a valid UUID format
    """
    if isinstance(value, uuid.UUID):
        return str(value)

    if not isinstance(value, str):
        raise ValueError(f"Expected UUID or str, got {type(value).__name__}")

    try:
        uuid.UUID(value)
        return value
    except ValueError:
        raise ValueError(f"Invalid UUID format: {value}")


def to_jsonable(value: Any) -> JsonType:
    """Convert complex types to JSON-serializable format.

    Handles datetime, date, Decimal, UUID, dict, and list types.

    Args:
        value: The value to convert

    Returns:
        JSON-serializable value
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]

    return str(value)


def validate_json_payload(_key: str, value: Any) -> Any:
    """Convert complex types to JSON-serializable format.

    This validator handles datetime and UUID objects in JSON columns,
    converting them to ISO format strings for storage.

    Args:
        _key: The field name being validated (unused, required by SQLAlchemy)
        value: The value to validate

    Returns:
        JSON-serializable value
    """
    return to_jsonable(value)
