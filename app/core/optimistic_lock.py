"""
Optimistic locking utilities for concurrent modification detection.

Provides helper functions to check and increment version numbers
when updating entities to detect concurrent modifications.

Note: RuleSet no longer has a version column (moved to RuleSetVersion).
Use check_ruleset_version for RuleSetVersion optimistic locking.

Supports both sync and async SQLAlchemy sessions.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.models import Rule, RuleSetVersion


class ConcurrentModificationError(ConflictError):
    """
    Raised when an update fails due to concurrent modification.

    This occurs when the expected version doesn't match the current
    version in the database, indicating another transaction modified
    the entity after it was read.
    """

    def __init__(
        self, entity_type: str, entity_id: str, expected_version: int, actual_version: int
    ):
        super().__init__(
            f"{entity_type} was modified by another transaction. Please refresh and try again.",
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "expected_version": expected_version,
                "actual_version": actual_version,
            },
        )
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.expected_version = expected_version
        self.actual_version = actual_version


def check_rule_version(db: Session, rule_id: Any, expected_version: int) -> Rule:
    """
    Check that a Rule's version matches the expected value before updating.

    This is the core optimistic locking check for Rule entities.
    Must be called within the same transaction that will update the rule.

    Args:
        db: Database session
        rule_id: Rule UUID to check
        expected_version: Expected version number (from when entity was read)

    Returns:
        The Rule entity if version matches

    Raises:
        NotFoundError: If rule doesn't exist
        ConcurrentModificationError: If version doesn't match (concurrent modification)

    Example:
        # Load rule
        rule = get_rule(db, rule_id="...")
        version_at_read = rule.version

        # ... time passes ...

        # Before update, check version
        rule = check_rule_version(db, rule_id, version_at_read)

        # Now safe to update
        rule.status = "APPROVED"
        db.flush()  # Trigger will auto-increment version
    """
    from app.core.errors import NotFoundError

    stmt = select(Rule).where(Rule.rule_id == rule_id)
    rule = (db.execute(stmt)).scalar_one_or_none()

    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(rule_id)})

    if rule.version != expected_version:
        raise ConcurrentModificationError(
            entity_type="Rule",
            entity_id=str(rule_id),
            expected_version=expected_version,
            actual_version=rule.version,
        )

    return rule


def check_ruleset_version(
    db: Session, ruleset_version_id: Any, expected_version: int
) -> RuleSetVersion:
    """
    Check that a RuleSetVersion's version matches the expected value before updating.

    This is the core optimistic locking check for RuleSetVersion entities.
    Must be called within the same transaction that will update the ruleset version.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID to check
        expected_version: Expected version number (from when entity was read)

    Returns:
        The RuleSetVersion entity if version matches

    Raises:
        NotFoundError: If ruleset version doesn't exist
        ConcurrentModificationError: If version doesn't match (concurrent modification)
    """
    from app.core.errors import NotFoundError

    stmt = select(RuleSetVersion).where(RuleSetVersion.ruleset_version_id == ruleset_version_id)
    ruleset_version = (db.execute(stmt)).scalar_one_or_none()

    if not ruleset_version:
        raise NotFoundError(
            "Ruleset version not found", details={"ruleset_version_id": str(ruleset_version_id)}
        )

    if ruleset_version.version != expected_version:
        raise ConcurrentModificationError(
            entity_type="RuleSetVersion",
            entity_id=str(ruleset_version_id),
            expected_version=expected_version,
            actual_version=ruleset_version.version,
        )

    return ruleset_version


async def check_rule_version_async(db: AsyncSession, rule_id: Any, expected_version: int) -> Rule:
    """
    Check that a Rule's version matches the expected value before updating (async version).

    This is the core optimistic locking check for Rule entities.
    Must be called within the same transaction that will update the rule.

    Args:
        db: Async database session
        rule_id: Rule UUID to check
        expected_version: Expected version number (from when entity was read)

    Returns:
        The Rule entity if version matches

    Raises:
        NotFoundError: If rule doesn't exist
        ConcurrentModificationError: If version doesn't match (concurrent modification)
    """
    from app.core.errors import NotFoundError

    stmt = select(Rule).where(Rule.rule_id == rule_id)
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    if not rule:
        raise NotFoundError("Rule not found", details={"rule_id": str(rule_id)})

    if rule.version != expected_version:
        raise ConcurrentModificationError(
            entity_type="Rule",
            entity_id=str(rule_id),
            expected_version=expected_version,
            actual_version=rule.version,
        )

    return rule


async def check_ruleset_version_async(
    db: AsyncSession, ruleset_version_id: Any, expected_version: int
) -> RuleSetVersion:
    """
    Check that a RuleSetVersion's version matches the expected value before updating (async version).

    This is the core optimistic locking check for RuleSetVersion entities.
    Must be called within the same transaction that will update the ruleset version.

    Args:
        db: Async database session
        ruleset_version_id: RuleSetVersion UUID to check
        expected_version: Expected version number (from when entity was read)

    Returns:
        The RuleSetVersion entity if version matches

    Raises:
        NotFoundError: If ruleset version doesn't exist
        ConcurrentModificationError: If version doesn't match (concurrent modification)
    """
    from app.core.errors import NotFoundError

    stmt = select(RuleSetVersion).where(RuleSetVersion.ruleset_version_id == ruleset_version_id)
    result = await db.execute(stmt)
    ruleset_version = result.scalar_one_or_none()

    if not ruleset_version:
        raise NotFoundError(
            "Ruleset version not found", details={"ruleset_version_id": str(ruleset_version_id)}
        )

    if ruleset_version.version != expected_version:
        raise ConcurrentModificationError(
            entity_type="RuleSetVersion",
            entity_id=str(ruleset_version_id),
            expected_version=expected_version,
            actual_version=ruleset_version.version,
        )

    return ruleset_version
