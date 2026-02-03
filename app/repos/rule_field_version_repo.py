"""
Repository layer for RuleFieldVersion data access.

Provides database operations following the repository pattern.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.models import RuleField, RuleFieldVersion

logger = logging.getLogger(__name__)


# ============================================================================
# RuleFieldVersion Repository Functions
# ============================================================================


async def get_all_field_versions(
    db: AsyncSession, field_key: str | None = None, status: str | None = None
) -> list[RuleFieldVersion]:
    """
    Retrieve all field versions, optionally filtered by field_key or status.

    Args:
        db: Database session
        field_key: Optional field key to filter by
        status: Optional status to filter by

    Returns:
        List of RuleFieldVersion models
    """
    query = select(RuleFieldVersion)

    if field_key:
        query = query.where(RuleFieldVersion.field_key == field_key)

    if status:
        query = query.where(RuleFieldVersion.status == status)

    query = query.order_by(RuleFieldVersion.field_key, RuleFieldVersion.version.desc())
    result = await db.execute(query)
    versions = result.scalars().all()

    logger.info(f"Retrieved {len(versions)} field versions")
    return list(versions)


async def get_field_version(db: AsyncSession, rule_field_version_id: str) -> RuleFieldVersion:
    """
    Retrieve a single field version by its ID.

    Args:
        db: Database session
        rule_field_version_id: UUID of the field version

    Returns:
        RuleFieldVersion model

    Raises:
        NotFoundError: If field version does not exist
    """
    stmt = select(RuleFieldVersion).where(
        RuleFieldVersion.rule_field_version_id == rule_field_version_id
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        logger.warning(f"Field version not found: {rule_field_version_id}")
        raise NotFoundError(
            f"Field version '{rule_field_version_id}' not found",
            details={"rule_field_version_id": rule_field_version_id},
        )

    logger.debug(f"Retrieved field version: {rule_field_version_id}")
    return version


async def get_latest_approved_version(db: AsyncSession, field_key: str) -> RuleFieldVersion | None:
    """
    Retrieve the latest APPROVED version for a field.

    Args:
        db: Database session
        field_key: Field identifier

    Returns:
        RuleFieldVersion model or None if no approved version exists
    """
    stmt = (
        select(RuleFieldVersion)
        .where(
            RuleFieldVersion.field_key == field_key,
            RuleFieldVersion.status == "APPROVED",
        )
        .order_by(RuleFieldVersion.version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()

    if version:
        logger.debug(f"Retrieved latest approved version for field: {field_key}")
    else:
        logger.debug(f"No approved version found for field: {field_key}")

    return version


async def get_all_approved_versions(db: AsyncSession) -> list[RuleFieldVersion]:
    """
    Retrieve all APPROVED field versions for registry compilation.

    Args:
        db: Database session

    Returns:
        List of APPROVED RuleFieldVersion models
    """
    stmt = (
        select(RuleFieldVersion)
        .where(RuleFieldVersion.status == "APPROVED")
        .order_by(RuleFieldVersion.field_id)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    logger.info(f"Retrieved {len(versions)} approved field versions for registry")
    return list(versions)


async def get_field_version_by_key_and_version(
    db: AsyncSession, field_key: str, version: int
) -> RuleFieldVersion:
    """
    Retrieve a field version by field key and version number.

    Args:
        db: Database session
        field_key: Field identifier
        version: Version number

    Returns:
        RuleFieldVersion model

    Raises:
        NotFoundError: If field version does not exist
    """
    stmt = select(RuleFieldVersion).where(
        RuleFieldVersion.field_key == field_key,
        RuleFieldVersion.version == version,
    )
    result = await db.execute(stmt)
    version_obj = result.scalar_one_or_none()

    if not version_obj:
        logger.warning(f"Field version not found: {field_key} v{version}")
        raise NotFoundError(
            f"Field version '{field_key}' v{version} not found",
            details={"field_key": field_key, "version": version},
        )

    logger.debug(f"Retrieved field version: {field_key} v{version}")
    return version_obj


async def create_field_version(
    db: AsyncSession, field_key: str, version_data: dict[str, Any], created_by: str
) -> RuleFieldVersion:
    """
    Create a new field version.

    Args:
        db: Database session
        field_key: Field identifier
        version_data: Dictionary with field data
        created_by: User creating the version

    Returns:
        Created RuleFieldVersion model

    Raises:
        NotFoundError: If field does not exist
        ConflictError: If version already exists
    """
    import uuid

    # Get the field to verify it exists and get field_id
    result = await db.execute(select(RuleField).where(RuleField.field_key == field_key))
    field = result.scalar_one_or_none()

    if not field:
        raise NotFoundError(
            f"Field '{field_key}' not found",
            details={"field_key": field_key},
        )

    # Calculate next version number
    result = await db.execute(
        select(RuleFieldVersion.version)
        .where(RuleFieldVersion.field_key == field_key)
        .order_by(RuleFieldVersion.version.desc())
        .limit(1)
    )
    max_version = result.scalar_one_or_none()

    next_version = (max_version or 0) + 1

    # Create the version
    field_version = RuleFieldVersion(
        rule_field_version_id=str(uuid.uuid7()),
        field_key=field_key,
        version=next_version,
        field_id=field.field_id,
        display_name=version_data.get("display_name", field.display_name),
        description=version_data.get("description"),
        data_type=version_data.get("data_type", field.data_type),
        allowed_operators=version_data.get("allowed_operators", field.allowed_operators),
        multi_value_allowed=version_data.get("multi_value_allowed", field.multi_value_allowed),
        is_sensitive=version_data.get("is_sensitive", field.is_sensitive),
        status="DRAFT",
        created_by=created_by,
        created_at=datetime.now(UTC),
    )

    try:
        db.add(field_version)
        await db.flush()

        # Update the parent field's current_version and version
        field.current_version = next_version
        field.version += 1
        await db.flush()

        logger.info(f"Created field version: {field_key} v{next_version}")
        return field_version

    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict creating field version: {field_key} v{next_version}")
        raise ConflictError(
            f"Field version '{field_key}' v{next_version} already exists",
            details={"field_key": field_key, "version": next_version},
        )


async def update_field_version_status(
    db: AsyncSession,
    rule_field_version_id: str,
    status: str,
    approved_by: str | None = None,
) -> RuleFieldVersion:
    """
    Update the status of a field version.

    Args:
        db: Database session
        rule_field_version_id: UUID of the field version
        status: New status (PENDING_APPROVAL, APPROVED, REJECTED, etc.)
        approved_by: Approver's user ID (required for APPROVED status)

    Returns:
        Updated RuleFieldVersion model

    Raises:
        NotFoundError: If field version does not exist
    """
    version = await get_field_version(db, rule_field_version_id)

    version.status = status

    if status == "APPROVED" and approved_by:
        version.approved_by = approved_by
        version.approved_at = datetime.now(UTC)
    elif status == "REJECTED" and approved_by:
        version.approved_by = approved_by
        version.approved_at = datetime.now(UTC)

    await db.flush()

    logger.info(
        f"Updated field version status: {rule_field_version_id} to {status}",
        extra={"rule_field_version_id": rule_field_version_id, "status": status},
    )

    return version


async def get_pending_approval_field_versions(
    db: AsyncSession, limit: int = 100
) -> list[RuleFieldVersion]:
    """
    Retrieve field versions pending approval.

    Args:
        db: Database session
        limit: Maximum number of results

    Returns:
        List of RuleFieldVersion models with PENDING_APPROVAL status
    """
    stmt = (
        select(RuleFieldVersion)
        .where(RuleFieldVersion.status == "PENDING_APPROVAL")
        .order_by(RuleFieldVersion.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    logger.info(f"Retrieved {len(versions)} pending field versions")
    return list(versions)


async def delete_field_version(db: AsyncSession, rule_field_version_id: str) -> None:
    """
    Delete a field version (only DRAFT versions can be deleted).

    Args:
        db: Database session
        rule_field_version_id: UUID of the field version

    Raises:
        NotFoundError: If field version does not exist
    """
    version = await get_field_version(db, rule_field_version_id)

    if version.status != "DRAFT":
        raise ConflictError(
            f"Cannot delete field version with status {version.status}",
            details={"rule_field_version_id": rule_field_version_id, "status": version.status},
        )

    db.delete(version)
    await db.flush()

    logger.info(f"Deleted field version: {rule_field_version_id}")
