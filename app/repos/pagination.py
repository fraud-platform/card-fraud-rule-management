"""Shared utilities for keyset/cursor-based pagination."""

import base64
import json
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_

from app.api.schemas.keyset_pagination import CursorDirection


def encode_cursor(id: str, created_at: datetime) -> str:
    """Encode a cursor from ID and timestamp.

    Args:
        id: Entity ID (UUID)
        created_at: Creation timestamp

    Returns:
        Base64-encoded cursor string
    """
    cursor_data = {
        "id": str(id),
        "created_at": created_at.isoformat(),
    }
    json_str = json.dumps(cursor_data)
    return base64.b64encode(json_str.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> tuple[str, datetime]:
    """Decode a cursor into ID and timestamp.

    Args:
        cursor: Base64-encoded cursor string

    Returns:
        Tuple of (id, created_at)

    Raises:
        ValueError: If cursor is invalid or malformed
    """
    try:
        json_str = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
        cursor_data = json.loads(json_str)
        id = cursor_data["id"]
        created_at = datetime.fromisoformat(cursor_data["created_at"])
        return id, created_at
    except (KeyError, json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Invalid cursor: {e}") from e


def apply_cursor_filter(
    stmt: Select,
    model: Any,
    cursor: tuple[str, datetime] | None,
    direction: CursorDirection,
    order_column: str = "created_at",
    id_column: str | None = None,
) -> Select:
    """Apply keyset cursor filter to an existing query.

    This is a helper for applying cursor pagination to queries that already have
    filters and joins applied.

    Args:
        stmt: Existing SQLAlchemy Select statement
        model: SQLAlchemy model class
        cursor: Tuple of (id, created_at) for pagination cursor (None for first page)
        direction: NEXT or PREV
        order_column: Column to order by (default: created_at)
        id_column: ID column name (default: derived from model)

    Returns:
        Modified Select statement with cursor filter applied
    """
    if cursor is None:
        return stmt

    cursor_id, cursor_created_at = cursor

    # Get column objects
    order_col = getattr(model, order_column)
    id_col = getattr(model, id_column) if id_column else None

    if id_col is None:
        # Try to get from model's primary key
        if hasattr(model, "__table__") and model.__table__.primary_key.columns:
            id_col = list(model.__table__.primary_key.columns)[0]
        else:
            # Fallback convention
            id_col = getattr(model, f"{model.__name__.lower()}_id")

    if direction == CursorDirection.NEXT:
        stmt = stmt.where(
            or_(
                order_col < cursor_created_at,
                and_(order_col == cursor_created_at, id_col < cursor_id),
            )
        )
    else:
        stmt = stmt.where(
            or_(
                order_col > cursor_created_at,
                and_(order_col == cursor_created_at, id_col > cursor_id),
            )
        )

    return stmt


def build_keyset_query(
    model: Any,
    cursor: tuple[str, datetime] | None,
    direction: CursorDirection,
    limit: int,
    order_column: str = "created_at",
    id_column: str | None = None,
) -> Select:
    """Build a keyset pagination query with proper ordering.

    Args:
        model: SQLAlchemy model class
        cursor: Tuple of (id, created_at) for pagination cursor (None for first page)
        direction: NEXT or PREV
        limit: Number of items to return
        order_column: Column to order by (default: created_at)
        id_column: ID column name (default: derived from model)

    Returns:
        SQLAlchemy Select statement with proper ordering and filters
    """
    # Determine ID column name
    if id_column is None:
        # Try to get from model's primary key
        if hasattr(model, "__table__") and model.__table__.primary_key.columns:
            id_column = model.__table__.primary_key.columns.keys()[0]
        else:
            # Fallback convention
            id_column = f"{model.__name__.lower()}_id"

    # Get column objects
    order_col = getattr(model, order_column)
    id_col = getattr(model, id_column)

    # Start building the query
    # Order by created_at DESC, id DESC for consistent results
    stmt = Select(model).order_by(order_col.desc(), id_col.desc())

    # Apply cursor filter if provided
    if cursor is not None:
        cursor_id, cursor_created_at = cursor

        if direction == CursorDirection.NEXT:
            # For next page: get items AFTER the cursor
            # (created_at < cursor_created_at) OR
            # (created_at = cursor_created_at AND id < cursor_id)
            stmt = stmt.where(
                or_(
                    order_col < cursor_created_at,
                    and_(order_col == cursor_created_at, id_col < cursor_id),
                )
            )
        else:  # PREV
            # For prev page: get items BEFORE the cursor
            # (created_at > cursor_created_at) OR
            # (created_at = cursor_created_at AND id > cursor_id)
            stmt = stmt.where(
                or_(
                    order_col > cursor_created_at,
                    and_(order_col == cursor_created_at, id_col > cursor_id),
                )
            )

    # Apply limit
    stmt = stmt.limit(limit + 1)  # Fetch one extra to check if there are more

    return stmt


def get_keyset_page_info(
    items: list[Any],
    limit: int,
    direction: CursorDirection,
    is_first_page: bool = False,
) -> tuple[list[Any], bool, bool, str | None, str | None]:
    """Calculate pagination metadata from fetched items and trim the list.

    Args:
        items: List of items fetched (may include extra item)
        limit: Original limit requested
        direction: Pagination direction
        is_first_page: True if this is the first page (no cursor provided)

    Returns:
        Tuple of (trimmed_items, has_next, has_prev, next_cursor, prev_cursor)
    """
    has_more = len(items) > limit

    # Trim the extra item if present
    if has_more:
        items = items[:limit]

    trimmed_items = items
    has_next = False
    has_prev = False
    next_cursor = None
    prev_cursor = None

    if not items:
        return trimmed_items, has_next, has_prev, next_cursor, prev_cursor

    # Helper function to extract ID from an item
    def get_id(item: Any) -> str:
        """Extract ID from various model types."""
        if isinstance(item, dict):
            return item.get("approval_id") or item.get("audit_id") or item.get("id", "")
        if hasattr(item, "rule_id"):
            return str(item.rule_id)
        if hasattr(item, "ruleset_id"):
            return str(item.ruleset_id)
        if hasattr(item, "approval_id"):
            return str(item.approval_id)
        if hasattr(item, "audit_id"):
            return str(item.audit_id)
        return getattr(item, "id", "")

    # Helper function to extract timestamp from an item
    def get_timestamp(item: Any) -> datetime:
        """Extract timestamp from various model types."""
        if isinstance(item, dict):
            ts = item.get("created_at") or item.get("performed_at")
            if ts:
                return ts
        if hasattr(item, "created_at"):
            return item.created_at
        if hasattr(item, "performed_at"):
            return item.performed_at
        return datetime.utcnow()

    if direction == CursorDirection.NEXT:
        # Forward pagination
        has_next = has_more
        # has_prev is True only if we're NOT on the first page
        has_prev = not is_first_page

        if has_next:
            # Next cursor is based on the last item
            last_item = items[-1]
            next_cursor = encode_cursor(get_id(last_item), get_timestamp(last_item))

        # Prev cursor is based on the first item (only if not first page)
        if has_prev:
            first_item = items[0]
            prev_cursor = encode_cursor(get_id(first_item), get_timestamp(first_item))
    else:
        # Backward pagination
        has_prev = has_more
        has_next = True  # If we're going backward, we can always go forward

        if has_prev:
            # Prev cursor is based on the last item
            last_item = items[-1]
            prev_cursor = encode_cursor(get_id(last_item), get_timestamp(last_item))

        # Next cursor is based on the first item
        first_item = items[0]
        next_cursor = encode_cursor(get_id(first_item), get_timestamp(first_item))

    return trimmed_items, has_next, has_prev, next_cursor, prev_cursor
