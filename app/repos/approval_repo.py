"""
Repository helpers for approvals and audit log retrieval.

These are simple read functions used by the API layer. They intentionally
do not perform business mutations (these remain in `rule_repo.py`).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.keyset_pagination import CursorDirection
from app.core.errors import ValidationError
from app.db.models import Approval, AuditLog
from app.repos.pagination import apply_cursor_filter, decode_cursor, get_keyset_page_info

# Maximum values for pagination
MAX_AUDIT_LOG_LIMIT = 1000


async def list_approvals(
    db: AsyncSession,
    *,
    status: str | None = None,
    entity_type: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    direction: CursorDirection = CursorDirection.NEXT,
) -> tuple[list[dict], bool, bool, str | None, str | None]:
    """List approvals with keyset/cursor-based pagination.

    Args:
        db: Database session
        status: Filter by approval status
        entity_type: Filter by entity type
        cursor: Base64-encoded cursor from previous page
        limit: Number of items per page
        direction: NEXT for forward pagination, PREV for backward

    Returns:
        Tuple of (list of approval dicts, has_next, has_prev, next_cursor, prev_cursor)
    """
    from app.db.models import RuleSetVersion, RuleVersion

    # Decode cursor if provided
    cursor_tuple = None
    is_first_page = cursor is None
    if cursor:
        cursor_tuple = decode_cursor(cursor)

    # Build query with LEFT JOINs to RuleVersion and RuleSetVersion
    # This fetches rule_id and ruleset_id in a single query instead of N+1 queries
    stmt = (
        select(
            Approval.approval_id,
            Approval.entity_type,
            Approval.entity_id,
            Approval.action,
            Approval.maker,
            Approval.checker,
            Approval.status,
            Approval.remarks,
            Approval.created_at,
            Approval.decided_at,
            RuleVersion.rule_id,
            RuleSetVersion.ruleset_id,
        )
        .outerjoin(RuleVersion, Approval.entity_id == RuleVersion.rule_version_id)
        .outerjoin(RuleSetVersion, Approval.entity_id == RuleSetVersion.ruleset_version_id)
    )

    if status is not None:
        stmt = stmt.where(Approval.status == status)
    if entity_type is not None:
        stmt = stmt.where(Approval.entity_type == entity_type)

    # Apply keyset filter if cursor provided
    stmt = apply_cursor_filter(
        stmt, Approval, cursor_tuple, direction, order_column="created_at", id_column="approval_id"
    )

    # Order by created_at DESC, approval_id DESC
    stmt = stmt.order_by(Approval.created_at.desc(), Approval.approval_id.desc())

    # Apply limit (fetch one extra to check if there are more)
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    rows = result.all()

    # Convert rows to dicts
    approval_dicts = []
    for row in rows:
        approval_dict = {
            "approval_id": row.approval_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "action": row.action,
            "maker": row.maker,
            "checker": row.checker,
            "status": row.status,
            "remarks": row.remarks,
            "created_at": row.created_at,
            "decided_at": row.decided_at,
        }
        if row.entity_type == "RULE_VERSION":
            if row.rule_id is not None:
                approval_dict["rule_id"] = row.rule_id
        elif row.entity_type == "RULESET_VERSION":
            if row.ruleset_id is not None:
                approval_dict["ruleset_id"] = row.ruleset_id
        approval_dicts.append(approval_dict)

    # Calculate pagination metadata and trim list
    trimmed_approvals, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
        approval_dicts, limit, direction, is_first_page=is_first_page
    )

    return trimmed_approvals, has_next, has_prev, next_cursor, prev_cursor


async def list_audit_logs(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: Any | None = None,
    action: str | None = None,
    performed_by: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
    direction: CursorDirection = CursorDirection.NEXT,
) -> tuple[list[AuditLog], bool, bool, str | None, str | None]:
    """List audit logs with keyset/cursor-based pagination.

    Args:
        db: Database session
        entity_type: Filter by entity type
        entity_id: Filter by entity ID
        action: Filter by action
        performed_by: Filter by performer
        since: Filter by start date
        until: Filter by end date
        cursor: Base64-encoded cursor from previous page
        limit: Number of items per page
        direction: NEXT for forward pagination, PREV for backward

    Returns:
        Tuple of (list of audit logs, has_next, has_prev, next_cursor, prev_cursor)
    """
    # Validate limit parameter
    if limit < 1:
        raise ValidationError(
            "Invalid limit parameter", details={"limit": limit, "message": "limit must be >= 1"}
        )
    if limit > MAX_AUDIT_LOG_LIMIT:
        raise ValidationError(
            "limit exceeds maximum",
            details={"limit": limit, "max": MAX_AUDIT_LOG_LIMIT},
        )

    # Decode cursor if provided
    cursor_tuple = None
    is_first_page = cursor is None
    if cursor:
        cursor_tuple = decode_cursor(cursor)

    # Build query
    stmt = select(AuditLog)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if performed_by is not None:
        stmt = stmt.where(AuditLog.performed_by == performed_by)
    if since is not None:
        stmt = stmt.where(AuditLog.performed_at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.performed_at <= until)

    # Apply keyset filter if cursor provided
    stmt = apply_cursor_filter(
        stmt, AuditLog, cursor_tuple, direction, order_column="performed_at", id_column="audit_id"
    )

    # Order by performed_at DESC, audit_id DESC
    stmt = stmt.order_by(AuditLog.performed_at.desc(), AuditLog.audit_id.desc())

    # Apply limit (fetch one extra to check if there are more)
    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    audit_logs = result.scalars().all()

    # Convert to list for indexing
    logs_list = list(audit_logs)

    # Calculate pagination metadata and trim list
    trimmed_logs, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
        logs_list, limit, direction, is_first_page=is_first_page
    )

    return trimmed_logs, has_next, has_prev, next_cursor, prev_cursor
