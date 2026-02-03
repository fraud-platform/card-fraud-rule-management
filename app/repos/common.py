"""
Common repository functions shared across multiple repos.

This module contains utility functions that are used by multiple
repository modules to avoid code duplication.

All functions are async - use AsyncSession from SQLAlchemy.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import create_audit_log_async
from app.core.errors import MakerCheckerViolation
from app.core.optimistic_lock import (
    ConcurrentModificationError,
    check_rule_version_async,
    check_ruleset_version_async,
)
from app.db.models import Approval, Rule
from app.domain.enums import ApprovalStatus

__all__ = [
    "get_pending_approval",
    "check_rule_version_async",
    "check_ruleset_version_async",
    "increment_rule_version",
    "ConcurrentModificationError",
    "check_maker_not_checker",
    "update_approval_approved",
    "create_approval_audit_log",
]


async def get_pending_approval(db: AsyncSession, *, entity_id: Any) -> Approval | None:
    """Return the pending approval for the given entity, if any.

    Args:
        db: Async database session
        entity_id: The ID of the entity to find pending approval for

    Returns:
        The pending Approval record if found, None otherwise
    """
    stmt = select(Approval).where(
        Approval.entity_id == entity_id, Approval.status == ApprovalStatus.PENDING
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def increment_rule_version(db: AsyncSession, *, rule_id: Any) -> int:
    """
    Increment the optimistic version of a Rule.

    This should be called after any update operation on a rule to increment
    its version counter. This is done atomically to ensure consistency.

    Args:
        db: Async database session
        rule_id: The ID of the rule to increment version for

    Returns:
        The new version number
    """
    stmt = (
        update(Rule)
        .where(Rule.rule_id == rule_id)
        .values(version=Rule.version + 1)
        .returning(Rule.version)
    )
    result = await db.execute(stmt)
    new_version = result.scalar_one()
    await db.flush()
    return new_version


def check_maker_not_checker(maker: str, checker: str) -> None:
    """Ensure maker is not the same as checker.

    Args:
        maker: The user who created/submitted the entity
        checker: The user performing the approval

    Raises:
        MakerCheckerViolation: If maker == checker
    """
    if maker == checker:
        raise MakerCheckerViolation("Maker cannot approve their own submission")


async def update_approval_approved(
    db: AsyncSession,
    approval: Approval,
    checker: str,
    remarks: str | None = None,
) -> None:
    """Update an approval record to APPROVED status.

    Args:
        db: Async database session
        approval: The approval record to update
        checker: The user performing the approval
        remarks: Optional remarks for the approval
    """
    now = datetime.now(UTC)
    approval.checker = checker
    approval.status = ApprovalStatus.APPROVED
    approval.decided_at = now
    if remarks:
        approval.remarks = remarks


async def create_approval_audit_log(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    checker: str,
    old_value: dict,
    new_value: dict,
    include_details: dict | None = None,
) -> None:
    """Create an audit log entry for an approval action.

    Args:
        db: Async database session
        entity_type: Type of entity (e.g., "RULE_VERSION", "RULESET_VERSION")
        entity_id: ID of the entity
        checker: User performing the approval
        old_value: Snapshot of entity before change
        new_value: Snapshot of entity after change
        include_details: Optional additional details to include in audit
    """
    final_new_value = {**new_value}
    if include_details:
        final_new_value.update(include_details)

    await create_audit_log_async(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action="APPROVE",
        old_value=old_value,
        new_value=final_new_value,
        performed_by=checker,
    )
