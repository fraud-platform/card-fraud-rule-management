from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.approval import ApprovalResponse, AuditLogResponse
from app.api.schemas.keyset_pagination import (
    CursorDirection,
    KeysetPaginatedResponse,
)
from app.core.dependencies import AsyncDbSession, CurrentUser
from app.repos.approval_repo import (
    list_approvals,
    list_audit_logs,
)

router = APIRouter(tags=["approvals"])


@router.get("/approvals")
async def get_approvals(
    db: AsyncDbSession,
    user: CurrentUser,
    status: str | None = None,
    entity_type: str | None = None,
    cursor: Annotated[
        str | None, Query(description="Base64-encoded cursor from previous page")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Number of items per page (max 100)")
    ] = 50,
    direction: Annotated[
        CursorDirection, Query(description="Pagination direction")
    ] = CursorDirection.NEXT,
) -> KeysetPaginatedResponse[ApprovalResponse]:
    """List approvals with optional filters and keyset pagination.

    Uses cursor-based pagination for efficient data retrieval.

    **Parameters:**
    - `status`: Filter by approval status (e.g., "pending", "approved", "rejected")
    - `entity_type`: Filter by entity type (e.g., "rule", "ruleset")
    - `cursor`: Optional cursor from previous page response
    - `limit`: Number of items per page (default: 50, max: 100)
    - `direction`: "next" for forward pagination, "prev" for backward

    **Examples:**
        - First page: GET /approvals?limit=50
        - Filtered: GET /approvals?status=pending&entity_type=rule
        - Next page: GET /approvals?cursor=abc123&limit=50&direction=next
    """
    approval_dicts, has_next, has_prev, next_cursor, prev_cursor = await list_approvals(
        db,
        status=status,
        entity_type=entity_type,
        cursor=cursor,
        limit=limit,
        direction=direction,
    )

    items = [ApprovalResponse(**a) for a in approval_dicts]
    return KeysetPaginatedResponse[ApprovalResponse](
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


@router.get("/audit-log")
async def get_audit_log(
    db: AsyncDbSession,
    user: CurrentUser,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    performed_by: str | None = None,
    since: str | None = None,
    until: str | None = None,
    cursor: Annotated[
        str | None, Query(description="Base64-encoded cursor from previous page")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Number of items per page (max 1000)")
    ] = 100,
    direction: Annotated[
        CursorDirection, Query(description="Pagination direction")
    ] = CursorDirection.NEXT,
) -> KeysetPaginatedResponse[AuditLogResponse]:
    """List audit log with optional filters and keyset pagination.

    Uses cursor-based pagination for efficient data retrieval.

    **Parameters:**
    - `entity_type`: Filter by entity type (e.g., "rule", "ruleset")
    - `entity_id`: Filter by specific entity ID
    - `action`: Filter by action type (e.g., "create", "update", "approve")
    - `performed_by`: Filter by user who performed the action
    - `since`: ISO 8601 datetime filter (start of range)
    - `until`: ISO 8601 datetime filter (end of range)
    - `cursor`: Optional cursor from previous page response
    - `limit`: Number of items per page (default: 100, max: 1000)
    - `direction`: "next" for forward pagination, "prev" for backward

    **Examples:**
        - First page: GET /audit-log?limit=100
        - Filtered: GET /audit-log?action=approve&since=2024-01-01T00:00:00Z
        - Next page: GET /audit-log?cursor=abc123&limit=100&direction=next
    """

    def _parse_dt(value: str | None) -> datetime | None:
        if value is None:
            return None
        # Many clients forget to URL-encode '+' in ISO 8601 offsets, so it arrives as a space.
        normalized = value.replace(" ", "+")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as err:
            # Treat invalid date formats as client errors
            raise HTTPException(status_code=422, detail=f"Invalid date format: {value}") from err

    audit_logs, has_next, has_prev, next_cursor, prev_cursor = await list_audit_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        performed_by=performed_by,
        since=_parse_dt(since),
        until=_parse_dt(until),
        cursor=cursor,
        limit=limit,
        direction=direction,
    )

    items = [AuditLogResponse.model_validate(log) for log in audit_logs]
    return KeysetPaginatedResponse[AuditLogResponse](
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )
