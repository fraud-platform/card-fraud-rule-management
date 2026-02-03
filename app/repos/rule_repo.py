"""
Repository functions for Rule and RuleVersion entities.

Minimal implementations to support create/list/get and version lifecycle.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.keyset_pagination import CursorDirection
from app.core.audit import create_audit_log_async, snapshot_entity
from app.core.errors import ConflictError, NotFoundError
from app.core.notifications import notify
from app.core.optimistic_lock import check_rule_version_async
from app.db.models import Approval, Rule, RuleVersion
from app.domain.enums import EntityStatus
from app.repos.common import (
    check_maker_not_checker,
    create_approval_audit_log,
    get_pending_approval,
    increment_rule_version,
    update_approval_approved,
)
from app.repos.pagination import build_keyset_query, decode_cursor, get_keyset_page_info

# Constants for common messages
RULE_VERSION_NOT_FOUND = "RuleVersion not found"

logger = logging.getLogger(__name__)

RULE_TYPE_DEFAULT_ACTION = {
    "ALLOWLIST": "APPROVE",
    "BLOCKLIST": "DECLINE",
    "AUTH": "DECLINE",
    "MONITORING": "REVIEW",
}

RULE_TYPE_VALID_ACTIONS = {
    "ALLOWLIST": ["APPROVE"],
    "BLOCKLIST": ["DECLINE"],
    "AUTH": ["APPROVE", "DECLINE"],
    "MONITORING": ["REVIEW"],
}


def _get_default_action(rule_type: str) -> str:
    return RULE_TYPE_DEFAULT_ACTION.get(rule_type, "REVIEW")


def _validate_action_for_rule_type(rule_type: str, action: str) -> None:
    allowed = RULE_TYPE_VALID_ACTIONS.get(rule_type, [])
    if allowed and action not in allowed:
        raise ConflictError(
            f"{rule_type} rules must have action in {allowed}. Got: {action}",
            details={"rule_type": rule_type, "action": action},
        )


def _rule_version_summary(version: RuleVersion) -> dict:
    return {
        "rule_id": str(version.rule_id),
        "version": version.version,
        "priority": version.priority,
    }


async def list_rules(
    db: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = 50,
    direction: CursorDirection = CursorDirection.NEXT,
) -> tuple[list[Rule], bool, bool, str | None, str | None]:
    """List rules with keyset/cursor-based pagination.

    Args:
        db: Database session
        cursor: Base64-encoded cursor from previous page
        limit: Number of items per page
        direction: NEXT for forward pagination, PREV for backward

    Returns:
        Tuple of (list of rules, has_next, has_prev, next_cursor, prev_cursor)
    """
    # Decode cursor if provided
    cursor_tuple = None
    is_first_page = cursor is None
    if cursor:
        cursor_tuple = decode_cursor(cursor)

    # Build query with keyset pagination
    # Order by created_at DESC, rule_id DESC for consistent results
    stmt = build_keyset_query(
        Rule,
        cursor=cursor_tuple,
        direction=direction,
        limit=limit,
        order_column="created_at",
        id_column="rule_id",
    )

    # Execute query
    result = await db.execute(stmt)
    rules = result.scalars().all()

    # Convert to list for indexing
    rules_list = list(rules)

    # Calculate pagination metadata and trim list
    trimmed_rules, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
        rules_list, limit, direction, is_first_page=is_first_page
    )

    return trimmed_rules, has_next, has_prev, next_cursor, prev_cursor


async def get_rule(db: AsyncSession, rule_id: Any) -> Rule:
    stmt = select(Rule).where(Rule.rule_id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(rule_id)})
    return rule


async def create_rule(
    db: AsyncSession,
    *,
    rule_name: str,
    description: str | None,
    rule_type: str,
    created_by: str,
    condition_tree: dict | None = None,
    priority: int = 100,
    action: str | None = None,
) -> Rule:
    # Set smart default action based on rule_type if not provided
    action = action or _get_default_action(rule_type)
    _validate_action_for_rule_type(rule_type, action)

    # Initialize rule and first version (DRAFT)
    rule = Rule(
        rule_name=rule_name,
        description=description,
        rule_type=rule_type,
        current_version=1,
        status="DRAFT",
        created_by=created_by,
    )

    try:
        db.add(rule)
        await db.flush()

        # create initial version
        version = RuleVersion(
            rule_id=rule.rule_id,
            version=1,
            condition_tree=condition_tree or {},
            priority=priority,
            action=action,
            created_by=created_by,
            status="DRAFT",
        )
        db.add(version)
        await db.flush()

        logger.info("Created rule %s with initial version", rule.rule_id)
        return rule

    except IntegrityError as e:
        await db.rollback()
        raise ConflictError("Rule creation failed", details={"error": str(e)})


async def create_rule_version(
    db: AsyncSession,
    *,
    rule_id: Any,
    condition_tree: dict,
    created_by: str,
    priority: int = 100,
    action: str | None = None,
    scope: dict | None = None,
    expected_rule_version: int | None = None,
) -> RuleVersion:
    # Check optimistic locking version if provided
    if expected_rule_version is not None:
        # This will raise ConflictError if version doesn't match
        await check_rule_version_async(db, rule_id=rule_id, expected_version=expected_rule_version)

    # First check if rule exists (before creating version to avoid FK violation)
    stmt = select(Rule).where(Rule.rule_id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(rule_id)})

    # Set smart default action based on rule_type if not provided
    action = action or _get_default_action(rule.rule_type)
    _validate_action_for_rule_type(rule.rule_type, action)

    # determine next version number
    stmt = select(func.coalesce(func.max(RuleVersion.version), 0)).where(
        RuleVersion.rule_id == rule_id
    )
    result = await db.execute(stmt)
    max_version = result.scalar_one()
    next_version = int(max_version) + 1

    version = RuleVersion(
        rule_id=rule_id,
        version=next_version,
        condition_tree=condition_tree,
        priority=priority,
        action=action,
        scope=scope or {},
        created_by=created_by,
        status="DRAFT",
    )
    db.add(version)
    await db.flush()

    # update rule.current_version to the new draft version
    rule.current_version = next_version

    # Increment the optimistic version of the rule (for concurrent edit detection)
    await increment_rule_version(db, rule_id=rule_id)

    await db.flush()

    logger.info("Created rule version %s for rule %s", version.rule_version_id, rule_id)
    return version


async def submit_rule_version(
    db: AsyncSession,
    *,
    rule_version_id: Any,
    maker: str,
    remarks: str | None = None,
    idempotency_key: str | None = None,
) -> RuleVersion:
    # mark version as PENDING_APPROVAL and create an Approval row
    stmt = select(RuleVersion).where(RuleVersion.rule_version_id == rule_version_id)
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        raise NotFoundError(
            "RuleVersion not found", details={"rule_version_id": str(rule_version_id)}
        )

    # Check for idempotency first. If the same idempotency_key was used previously for this entity,
    # treat this as a replay and return the existing state (even if the entity is no longer DRAFT).
    if idempotency_key:
        existing_stmt = select(Approval).where(
            Approval.entity_type == "RULE_VERSION",
            Approval.entity_id == version.rule_version_id,
            Approval.idempotency_key == idempotency_key,
        )
        existing_result = await db.execute(existing_stmt)
        existing_approval = existing_result.scalar_one_or_none()
        if existing_approval:
            # Idempotent request - return existing state without modification
            logger.info(
                "Idempotent submit detected for rule version %s with key %s, returning existing approval %s",
                rule_version_id,
                idempotency_key,
                existing_approval.approval_id,
            )
            return version

    if version.status not in (EntityStatus.DRAFT, EntityStatus.REJECTED):
        raise ConflictError(
            "Only DRAFT or REJECTED versions can be submitted",
            details={"status": version.status},
        )

    old_value = {**snapshot_entity(version, include=["status"]), **_rule_version_summary(version)}

    version.status = EntityStatus.PENDING_APPROVAL
    await db.flush()

    approval = Approval(
        entity_type="RULE_VERSION",
        entity_id=version.rule_version_id,
        action="SUBMIT",
        maker=maker,
        status="PENDING",
        remarks=remarks,
        idempotency_key=idempotency_key,
    )
    db.add(approval)
    await db.flush()

    await create_audit_log_async(
        db,
        entity_type="RULE_VERSION",
        entity_id=str(version.rule_version_id),
        action="SUBMIT",
        old_value=old_value,
        new_value={
            **snapshot_entity(version, include=["status"]),
            **_rule_version_summary(version),
        },
        performed_by=maker,
    )

    notify(
        "RULE_VERSION_SUBMITTED",
        entity_type="RULE_VERSION",
        entity_id=str(version.rule_version_id),
        actor=maker,
        details={"rule_id": str(version.rule_id), "version": version.version},
    )

    logger.info("Submitted rule version %s for approval", rule_version_id)
    return version


async def approve_rule_version(
    db: AsyncSession, *, rule_version_id: Any, checker: str, remarks: str | None = None
) -> RuleVersion:
    approval = await get_pending_approval(db, entity_id=rule_version_id)
    if not approval:
        raise NotFoundError(
            "Pending approval not found", details={"rule_version_id": str(rule_version_id)}
        )

    check_maker_not_checker(approval.maker, checker)

    from sqlalchemy.orm import joinedload

    stmt = (
        select(RuleVersion)
        .options(joinedload(RuleVersion.rule))  # Eager load to avoid N+1
        .where(RuleVersion.rule_version_id == rule_version_id)
    )
    result = await db.execute(stmt)
    version = result.unique().scalar_one_or_none()
    if not version:
        raise NotFoundError(
            RULE_VERSION_NOT_FOUND, details={"rule_version_id": str(rule_version_id)}
        )

    # Rule already loaded via joinedload
    rule = version.rule
    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(version.rule_id)})

    old_value = {
        **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
        **_rule_version_summary(version),
    }

    stmt_prev = select(RuleVersion).where(
        RuleVersion.rule_id == version.rule_id, RuleVersion.status == EntityStatus.APPROVED
    )
    prev_result = await db.execute(stmt_prev)
    prev_versions = prev_result.scalars().all()
    for pv in prev_versions:
        pv.status = EntityStatus.SUPERSEDED

    now = datetime.now(UTC)
    version.status = EntityStatus.APPROVED
    version.approved_by = checker
    version.approved_at = now

    await update_approval_approved(db, approval, checker, remarks)

    new_value = {
        **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
        **_rule_version_summary(version),
    }
    await create_approval_audit_log(
        db,
        entity_type="RULE_VERSION",
        entity_id=str(version.rule_version_id),
        checker=checker,
        old_value=old_value,
        new_value=new_value,
    )

    notify(
        "RULE_VERSION_APPROVED",
        entity_type="RULE_VERSION",
        entity_id=str(version.rule_version_id),
        actor=checker,
        details={"rule_id": str(version.rule_id), "version": version.version},
    )

    await increment_rule_version(db, rule_id=version.rule_id)

    await db.flush()
    return version


async def reject_rule_version(
    db: AsyncSession, *, rule_version_id: Any, checker: str, remarks: str | None = None
) -> RuleVersion:
    approval = await get_pending_approval(db, entity_id=rule_version_id)
    if not approval:
        raise NotFoundError(
            "Pending approval not found", details={"rule_version_id": str(rule_version_id)}
        )

    check_maker_not_checker(approval.maker, checker)

    stmt = select(RuleVersion).where(RuleVersion.rule_version_id == rule_version_id)
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        raise NotFoundError(
            RULE_VERSION_NOT_FOUND, details={"rule_version_id": str(rule_version_id)}
        )

    stmt = select(Rule).where(Rule.rule_id == version.rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(version.rule_id)})

    old_value = {
        **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
        **_rule_version_summary(version),
    }

    now = datetime.now(UTC)
    version.status = EntityStatus.REJECTED

    approval.checker = checker
    approval.status = "REJECTED"
    approval.decided_at = now
    if remarks:
        approval.remarks = remarks

    await create_audit_log_async(
        db,
        entity_type="RULE_VERSION",
        entity_id=str(version.rule_version_id),
        action="REJECT",
        old_value=old_value,
        new_value={
            **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
            **_rule_version_summary(version),
        },
        performed_by=checker,
    )

    notify(
        "RULE_VERSION_REJECTED",
        entity_type="RULE_VERSION",
        entity_id=str(version.rule_version_id),
        actor=checker,
        details={"rule_id": str(version.rule_id), "version": version.version},
    )

    await increment_rule_version(db, rule_id=version.rule_id)

    await db.flush()
    return version


async def get_rule_version(db: AsyncSession, rule_version_id: Any) -> RuleVersion:
    """Get a single rule version by ID (for analyst deep links)."""
    stmt = (
        select(RuleVersion)
        .options(selectinload(RuleVersion.rule))
        .where(RuleVersion.rule_version_id == rule_version_id)
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        raise NotFoundError(
            RULE_VERSION_NOT_FOUND, details={"rule_version_id": str(rule_version_id)}
        )
    return version


async def list_rule_versions(db: AsyncSession, rule_id: Any) -> list[RuleVersion]:
    """List all versions for a rule (for analyst deep links)."""
    stmt = (
        select(RuleVersion)
        .options(selectinload(RuleVersion.rule))
        .where(RuleVersion.rule_id == rule_id)
        .order_by(RuleVersion.version.desc())
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()
    if not versions:
        # Verify rule exists even if no versions
        rule_stmt = select(Rule).where(Rule.rule_id == rule_id)
        rule_result = await db.execute(rule_stmt)
        rule = rule_result.scalar_one_or_none()
        if not rule:
            raise NotFoundError("Rule not found", details={"rule_id": str(rule_id)})
    return list(versions)


async def get_rule_summary(db: AsyncSession, rule_id: Any) -> dict:
    """Get rule summary with latest version info (for analyst UI)."""
    stmt = select(Rule).where(Rule.rule_id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(rule_id)})

    # Get the latest (highest version number) rule_version
    stmt = (
        select(RuleVersion)
        .where(RuleVersion.rule_id == rule_id)
        .order_by(RuleVersion.version.desc())
        .limit(1)
    )
    latest_result = await db.execute(stmt)
    latest_version = latest_result.scalar_one_or_none()

    return {
        "rule_id": str(rule.rule_id),
        "rule_name": rule.rule_name,
        "rule_type": rule.rule_type,
        "status": rule.status,
        "latest_version": latest_version.version if latest_version else None,
        "latest_version_id": (str(latest_version.rule_version_id) if latest_version else None),
        "priority": latest_version.priority if latest_version else None,
        "action": latest_version.action if latest_version else None,
    }
