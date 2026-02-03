"""
API routes for RuleSet and RuleSetVersion operations.

Updated for v1 schema:
- RuleSet: Identity table (environment, region, country, rule_type)
- RuleSetVersion: Immutable snapshots with status
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.schemas.keyset_pagination import (
    CursorDirection,
    KeysetPaginatedResponse,
)
from app.api.schemas.ruleset import (
    CompiledAstResponse,
    RuleSetCreate,
    RuleSetResponse,
    RuleSetVersionActivateRequest,
    RuleSetVersionApproveRequest,
    RuleSetVersionCreate,
    RuleSetVersionRejectRequest,
    RuleSetVersionResponse,
    RuleSetVersionSubmitRequest,
)
from app.core.dependencies import AsyncDbSession, CurrentUser
from app.core.security import get_user_id, require_permission
from app.repos import ruleset_repo as repo

router = APIRouter(tags=["rulesets"])


# =============================================================================
# RuleSet Identity Routes
# =============================================================================


@router.post("/rulesets", status_code=status.HTTP_201_CREATED)
async def create_ruleset(
    payload: RuleSetCreate,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("ruleset:create"))],
) -> RuleSetResponse:
    """Create a new ruleset identity.

    The ruleset identity defines the scope (environment, region, country, rule_type)
    for which versions can be created. One ruleset per unique scope combination.
    """
    created_by = get_user_id(user)
    ruleset = await repo.create_ruleset(
        db,
        environment=payload.environment,
        region=payload.region,
        country=payload.country,
        rule_type=payload.rule_type,
        name=payload.name,
        description=payload.description,
        created_by=created_by,
    )
    await db.commit()
    return RuleSetResponse.model_validate(ruleset)


@router.get("/rulesets")
async def list_rulesets(
    db: AsyncDbSession,
    user: CurrentUser,
    cursor: Annotated[
        str | None, Query(description="Base64-encoded cursor from previous page")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Number of items per page")] = 50,
    direction: Annotated[
        CursorDirection, Query(description="Pagination direction")
    ] = CursorDirection.NEXT,
    rule_type: Annotated[str | None, Query(description="Filter by rule type")] = None,
    environment: Annotated[str | None, Query(description="Filter by environment")] = None,
    region: Annotated[str | None, Query(description="Filter by region")] = None,
    country: Annotated[str | None, Query(description="Filter by country")] = None,
) -> KeysetPaginatedResponse[RuleSetResponse]:
    """List ruleset identities with keyset pagination."""
    rulesets, has_next, has_prev, next_cursor, prev_cursor = await repo.list_rulesets(
        db,
        cursor=cursor,
        limit=limit,
        direction=direction,
        rule_type=rule_type,
        environment=environment,
        region=region,
        country=country,
    )

    return KeysetPaginatedResponse[RuleSetResponse](
        items=[RuleSetResponse.model_validate(rs) for rs in rulesets],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


@router.get("/rulesets/{ruleset_id}")
async def get_ruleset(
    ruleset_id: str,
    db: AsyncDbSession,
    user: CurrentUser,
) -> RuleSetResponse:
    """Get a ruleset identity by ID."""
    ruleset = await repo.get_ruleset(db, ruleset_id)
    return RuleSetResponse.model_validate(ruleset)


# =============================================================================
# RuleSet Version Routes
# =============================================================================


@router.get("/rulesets/{ruleset_id}/versions")
async def list_ruleset_versions(
    ruleset_id: str,
    db: AsyncDbSession,
    user: CurrentUser,
    cursor: Annotated[str | None, Query(description="Base64-encoded cursor")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    direction: Annotated[CursorDirection, Query()] = CursorDirection.NEXT,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
) -> KeysetPaginatedResponse[RuleSetVersionResponse]:
    """List all versions of a ruleset."""
    versions, has_next, has_prev, next_cursor, prev_cursor = await repo.list_ruleset_versions(
        db,
        ruleset_id=ruleset_id,
        cursor=cursor,
        limit=limit,
        direction=direction,
        status=status,
    )

    return KeysetPaginatedResponse[RuleSetVersionResponse](
        items=[RuleSetVersionResponse.model_validate(v) for v in versions],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


@router.post("/rulesets/{ruleset_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_ruleset_version(
    ruleset_id: str,
    payload: RuleSetVersionCreate,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("ruleset:update"))],
) -> RuleSetVersionResponse:
    """Create a new version of a ruleset.

    Creates a DRAFT version with the given rule versions attached.
    """
    created_by = get_user_id(user)

    # Create the version
    version = await repo.create_ruleset_version(db, ruleset_id=ruleset_id, created_by=created_by)

    # Attach rules if provided
    if payload.rule_version_ids:
        version = await repo.attach_rules_to_version(
            db,
            ruleset_version_id=str(version.ruleset_version_id),
            rule_version_ids=[str(v) for v in payload.rule_version_ids],
            modified_by=created_by,
        )

    await db.commit()
    return RuleSetVersionResponse.model_validate(version)


@router.get("/ruleset-versions/{ruleset_version_id}")
async def get_ruleset_version(
    ruleset_version_id: str,
    db: AsyncDbSession,
    user: CurrentUser,
) -> RuleSetVersionResponse:
    """Get a ruleset version by ID."""
    version = await repo.get_ruleset_version(db, ruleset_version_id, include_rules=True)
    return RuleSetVersionResponse.model_validate(version)


@router.post("/ruleset-versions/{ruleset_version_id}/submit")
async def submit_ruleset_version(
    ruleset_version_id: str,
    payload: RuleSetVersionSubmitRequest,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("ruleset:submit"))],
) -> RuleSetVersionResponse:
    """Submit a ruleset version for approval."""
    maker = get_user_id(user)
    version = await repo.submit_ruleset_version(
        db,
        ruleset_version_id=ruleset_version_id,
        maker=maker,
        idempotency_key=payload.idempotency_key,
    )
    await db.commit()
    return RuleSetVersionResponse.model_validate(version)


@router.post("/ruleset-versions/{ruleset_version_id}/approve")
async def approve_ruleset_version(
    ruleset_version_id: str,
    payload: RuleSetVersionApproveRequest,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("ruleset:approve"))],
) -> RuleSetVersionResponse:
    """Approve a ruleset version (triggers publishing to S3)."""
    checker = get_user_id(user)
    version = await repo.approve_ruleset_version(
        db,
        ruleset_version_id=ruleset_version_id,
        checker=checker,
    )
    await db.commit()
    return RuleSetVersionResponse.model_validate(version)


@router.post("/ruleset-versions/{ruleset_version_id}/reject")
async def reject_ruleset_version(
    ruleset_version_id: str,
    payload: RuleSetVersionRejectRequest,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("ruleset:reject"))],
) -> RuleSetVersionResponse:
    """Reject a ruleset version."""
    checker = get_user_id(user)
    version = await repo.reject_ruleset_version(
        db,
        ruleset_version_id=ruleset_version_id,
        checker=checker,
        remarks=payload.remarks,
    )
    await db.commit()
    return RuleSetVersionResponse.model_validate(version)


@router.post("/ruleset-versions/{ruleset_version_id}/activate")
async def activate_ruleset_version(
    ruleset_version_id: str,
    payload: RuleSetVersionActivateRequest,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("ruleset:activate"))],
) -> RuleSetVersionResponse:
    """Activate a ruleset version (makes it live for runtime)."""
    activated_by = get_user_id(user)
    version = await repo.activate_ruleset_version(
        db,
        ruleset_version_id=ruleset_version_id,
        activated_by=activated_by,
    )
    await db.commit()
    return RuleSetVersionResponse.model_validate(version)


@router.post("/ruleset-versions/{ruleset_version_id}/compile")
async def compile_ruleset_version(
    ruleset_version_id: str,
    db: AsyncDbSession,
    user: dict[str, Any] = Depends(require_permission("rule:read")),
) -> CompiledAstResponse:
    """Compile a ruleset version to AST (in-memory only, not stored)."""
    invoked_by = get_user_id(user)
    return CompiledAstResponse.model_validate(
        await repo.compile_ruleset_version(
            db, ruleset_version_id=ruleset_version_id, invoked_by=invoked_by
        )
    )
