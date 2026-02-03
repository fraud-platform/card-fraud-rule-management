from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.schemas.keyset_pagination import (
    CursorDirection,
    KeysetPaginatedResponse,
)
from app.api.schemas.rule import (
    RuleCreate,
    RuleResponse,
    RuleSimulateRequest,
    RuleSimulateResponse,
    RuleSummaryResponse,
    RuleVersionApproveRequest,
    RuleVersionCreate,
    RuleVersionDetailResponse,
    RuleVersionRejectRequest,
    RuleVersionResponse,
    RuleVersionSubmitRequest,
)
from app.core.dependencies import AsyncDbSession
from app.core.security import get_user_id, require_permission
from app.repos.rule_repo import (
    approve_rule_version,
    create_rule,
    create_rule_version,
    get_rule_summary,
    get_rule_version,
    list_rule_versions,
    list_rules,
    reject_rule_version,
    submit_rule_version,
)
from app.repos.rule_repo import (
    get_rule as repo_get_rule,
)

router = APIRouter(tags=["rules"])


@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def post_rule(
    payload: RuleCreate,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:create")),
):
    """
    Create a new rule with an initial DRAFT version.

    Requires `rule:create` permission.
    """
    created = await create_rule(
        db,
        rule_name=payload.rule_name,
        description=payload.description,
        rule_type=payload.rule_type,
        created_by=get_user_id(user),
        condition_tree=payload.condition_tree,
        priority=payload.priority,
        action=payload.action,
    )
    await db.commit()
    return created


@router.get("/rules")
async def get_rules(
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
    cursor: Annotated[
        str | None, Query(description="Base64-encoded cursor from previous page")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Number of items per page (max 100)")
    ] = 50,
    direction: Annotated[
        CursorDirection, Query(description="Pagination direction")
    ] = CursorDirection.NEXT,
) -> KeysetPaginatedResponse[RuleResponse]:
    """List all rules with keyset pagination.

    Requires `rule:read` permission.
    """
    rules, has_next, has_prev, next_cursor, prev_cursor = await list_rules(
        db,
        cursor=cursor,
        limit=limit,
        direction=direction,
    )

    return KeysetPaginatedResponse[RuleResponse](
        items=[RuleResponse.model_validate(r) for r in rules],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: str,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
):
    """Get a specific rule by ID.

    Requires `rule:read` permission.
    """
    return await repo_get_rule(db, rule_id)


@router.post(
    "/rules/{rule_id}/versions",
    response_model=RuleVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_rule_version(
    rule_id: str,
    payload: RuleVersionCreate,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:update")),
):
    """
    Create a new version of an existing rule.

    Requires `rule:update` permission.
    """
    v = await create_rule_version(
        db,
        rule_id=rule_id,
        condition_tree=payload.condition_tree,
        created_by=get_user_id(user),
        priority=payload.priority,
        action=payload.action,
        scope=payload.scope,
        expected_rule_version=payload.expected_rule_version,
    )
    await db.commit()
    return v


@router.post("/rule-versions/{rule_version_id}/submit", response_model=RuleVersionResponse)
async def submit_version(
    rule_version_id: str,
    payload: RuleVersionSubmitRequest,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:submit")),
):
    """
    Submit a rule version for approval.

    Requires `rule:submit` permission.
    """
    v = await submit_rule_version(
        db,
        rule_version_id=rule_version_id,
        maker=get_user_id(user),
        remarks=payload.remarks,
        idempotency_key=payload.idempotency_key,
    )
    await db.commit()
    return v


@router.post("/rule-versions/{rule_version_id}/approve", response_model=RuleVersionResponse)
async def approve_version(
    rule_version_id: str,
    payload: RuleVersionApproveRequest,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:approve")),
):
    """
    Approve a rule version.

    Requires `rule:approve` permission.
    """
    v = await approve_rule_version(
        db,
        rule_version_id=rule_version_id,
        checker=get_user_id(user),
        remarks=payload.remarks,
    )
    await db.commit()
    return v


@router.post("/rule-versions/{rule_version_id}/reject", response_model=RuleVersionResponse)
async def reject_version(
    rule_version_id: str,
    payload: RuleVersionRejectRequest,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:reject")),
):
    """
    Reject a rule version.

    Requires `rule:reject` permission.
    """
    v = await reject_rule_version(
        db,
        rule_version_id=rule_version_id,
        checker=get_user_id(user),
        remarks=payload.remarks,
    )
    await db.commit()
    return v


@router.get("/rule-versions/{rule_version_id}", response_model=RuleVersionDetailResponse)
async def get_rule_version_endpoint(
    rule_version_id: str,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
):
    """
    Get a specific rule version by ID (for analyst deep links).

    Returns rule version details including rule name, type, and condition tree.

    Requires `rule:read` permission.
    """
    version = await get_rule_version(db, rule_version_id)
    # Manually construct response to include rule_name and rule_type
    return RuleVersionDetailResponse(
        rule_id=str(version.rule_id),
        rule_version_id=str(version.rule_version_id),
        version=version.version,
        rule_name=version.rule.rule_name,
        rule_type=version.rule.rule_type,
        priority=version.priority,
        action=version.action,
        scope=version.scope,
        condition_tree=version.condition_tree,
        status=version.status,
        created_at=version.created_at,
        created_by=version.created_by,
        approved_at=version.approved_at,
        approved_by=version.approved_by,
    )


@router.get("/rules/{rule_id}/versions")
async def list_rule_versions_endpoint(
    rule_id: str,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
):
    """
    List all versions for a specific rule (for analyst deep links).

    Returns all rule versions ordered by version number (newest first).

    Requires `rule:read` permission.
    """
    versions = await list_rule_versions(db, rule_id)
    # Manually construct responses to include rule_name and rule_type
    return [
        RuleVersionDetailResponse(
            rule_id=str(v.rule_id),
            rule_version_id=str(v.rule_version_id),
            version=v.version,
            rule_name=v.rule.rule_name,
            rule_type=v.rule.rule_type,
            priority=v.priority,
            action=v.action,
            scope=v.scope,
            condition_tree=v.condition_tree,
            status=v.status,
            created_at=v.created_at,
            created_by=v.created_by,
            approved_at=v.approved_at,
            approved_by=v.approved_by,
        )
        for v in versions
    ]


@router.get("/rules/{rule_id}/summary", response_model=RuleSummaryResponse)
async def get_rule_summary_endpoint(
    rule_id: str,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
):
    """
    Get rule summary with latest version info (lightweight response for analyst UI).

    Returns rule metadata plus the latest version's priority and action.

    Requires `rule:read` permission.
    """
    summary = await get_rule_summary(db, rule_id)
    return RuleSummaryResponse.model_validate(summary)


@router.post("/rules/simulate", response_model=RuleSimulateResponse)
async def simulate_rule(
    payload: RuleSimulateRequest,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
):
    """
    Simulate a rule against historical transactions.

    This endpoint allows analysts to test a rule condition before submitting for approval.
    The simulation runs against historical transaction data.

    Note: This is a placeholder implementation. Full integration with transaction-management
    is required for actual simulation functionality.

    Requires `rule:read` permission.
    """
    from app.services.rule_simulation import simulate_rule_condition

    result = await simulate_rule_condition(
        db,
        rule_type=payload.rule_type.value,
        condition_tree=payload.condition_tree,
        scope=payload.scope,
        query=payload.query,
    )
    return RuleSimulateResponse.model_validate(result)
