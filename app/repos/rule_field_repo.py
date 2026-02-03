"""
Repository layer for RuleField and RuleFieldMetadata data access.

Provides database operations following the repository pattern to separate
data access logic from API endpoint handlers.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.rule_field import RuleFieldCreate, RuleFieldUpdate
from app.core.errors import ConflictError, NotFoundError
from app.db.models import RuleField, RuleFieldMetadata

logger = logging.getLogger(__name__)


# ============================================================================
# RuleField Repository Functions
# ============================================================================


async def get_all_rule_fields(db: AsyncSession) -> list[RuleField]:
    """
    Retrieve all rule fields.

    Args:
        db: Database session

    Returns:
        List of RuleField models
    """
    query = select(RuleField).order_by(RuleField.field_id)
    result = await db.execute(query)
    fields = result.scalars().all()

    logger.info(f"Retrieved {len(fields)} rule fields")
    return list(fields)


async def get_rule_field(db: AsyncSession, field_key: str) -> RuleField:
    """
    Retrieve a single rule field by its key.

    Args:
        db: Database session
        field_key: Unique field identifier

    Returns:
        RuleField model

    Raises:
        NotFoundError: If field does not exist
    """
    stmt = select(RuleField).where(RuleField.field_key == field_key)
    result = await db.execute(stmt)
    field = result.scalar_one_or_none()

    if not field:
        logger.warning(f"Rule field not found: {field_key}")
        raise NotFoundError(
            f"Rule field '{field_key}' not found",
            details={"field_key": field_key},
        )

    logger.debug(f"Retrieved rule field: {field_key}")
    return field


async def get_rule_field_by_id(db: AsyncSession, field_id: int) -> RuleField:
    """
    Retrieve a single rule field by its integer ID.

    Args:
        db: Database session
        field_id: Integer field identifier

    Returns:
        RuleField model

    Raises:
        NotFoundError: If field does not exist
    """
    stmt = select(RuleField).where(RuleField.field_id == field_id)
    result = await db.execute(stmt)
    field = result.scalar_one_or_none()

    if not field:
        logger.warning(f"Rule field not found: id={field_id}")
        raise NotFoundError(
            f"Rule field with id '{field_id}' not found",
            details={"field_id": field_id},
        )

    logger.debug(f"Retrieved rule field: id={field_id}")
    return field


async def get_next_field_id(db: AsyncSession) -> int:
    """
    Get the next available field_id.

    Standard fields use IDs 1-26. New custom fields start from 27.

    Args:
        db: Database session

    Returns:
        Next available field_id
    """
    result = await db.execute(select(func.max(RuleField.field_id)))
    max_id = result.scalar_one_or_none()

    next_id = (max_id or 26) + 1
    logger.debug(f"Next available field_id: {next_id}")
    return next_id


async def create_rule_field(db: AsyncSession, field: RuleFieldCreate, created_by: str) -> RuleField:
    """
    Create a new rule field with an initial DRAFT version.

    Args:
        db: Database session
        field: RuleFieldCreate schema with field data
        created_by: User creating the field

    Returns:
        Created RuleField model

    Raises:
        ConflictError: If field_key already exists

    Example:
        field_data = RuleFieldCreate(
            field_key="mcc",
            display_name="Merchant Category Code",
            data_type=DataType.STRING,
            allowed_operators=[Operator.EQ, Operator.IN]
        )
        new_field = create_rule_field(db, field_data, "user@example.com")
    """
    # Get next field_id
    next_field_id = await get_next_field_id(db)

    # Convert Pydantic model to dict and handle enum conversions
    field_data = field.model_dump()
    field_data["field_id"] = next_field_id
    field_data["created_by"] = created_by

    # Convert enums to string values for database storage
    if "data_type" in field_data:
        field_data["data_type"] = field_data["data_type"].value

    if "allowed_operators" in field_data:
        field_data["allowed_operators"] = [
            op.value if hasattr(op, "value") else op for op in field.allowed_operators
        ]

    db_field = RuleField(**field_data)

    try:
        db.add(db_field)
        await db.flush()  # Flush to detect conflicts before commit

        # Import here to avoid circular dependency
        from app.repos import rule_field_version_repo

        # Create initial DRAFT version
        await rule_field_version_repo.create_field_version(
            db,
            db_field.field_key,
            {
                "display_name": db_field.display_name,
                "description": db_field.description,
                "data_type": db_field.data_type,
                "allowed_operators": db_field.allowed_operators,
                "multi_value_allowed": db_field.multi_value_allowed,
                "is_sensitive": db_field.is_sensitive,
            },
            created_by,
        )

        logger.info(
            f"Created rule field: {field.field_key} with id={next_field_id}",
            extra={"field_key": field.field_key, "field_id": next_field_id},
        )
        return db_field

    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            f"Conflict creating rule field: {field.field_key}",
            extra={"error": str(e)},
        )
        raise ConflictError(
            f"Rule field '{field.field_key}' already exists",
            details={"field_key": field.field_key},
        )


async def update_rule_field(
    db: AsyncSession, field_key: str, updates: RuleFieldUpdate
) -> RuleField:
    """
    Update an existing rule field (partial update).

    Only provided fields are updated; omitted fields remain unchanged.
    field_key and field_id are immutable and cannot be updated.

    Updating a field creates a new DRAFT version.

    Args:
        db: Database session
        field_key: Unique field identifier
        updates: RuleFieldUpdate schema with fields to update

    Returns:
        Updated RuleField model

    Raises:
        NotFoundError: If field does not exist

    Example:
        updates = RuleFieldUpdate(display_name="Updated Field Name")
        updated_field = update_rule_field(db, "old_field", updates)
    """
    # First retrieve the field (will raise NotFoundError if not exists)
    db_field = await get_rule_field(db, field_key)

    # Extract only the fields that were actually provided (not None)
    update_data = updates.model_dump(exclude_unset=True)

    if not update_data:
        logger.debug(f"No updates provided for field: {field_key}")
        return db_field

    # Convert enums to string values for database storage
    if "data_type" in update_data:
        update_data["data_type"] = update_data["data_type"].value

    if "allowed_operators" in update_data:
        update_data["allowed_operators"] = [
            op.value if hasattr(op, "value") else op for op in update_data["allowed_operators"]
        ]

    # Apply updates to identity table
    for key, value in update_data.items():
        if key not in ("field_key", "field_id"):  # These are immutable
            setattr(db_field, key, value)

    db_field.version += 1
    db_field.updated_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        f"Updated rule field: {field_key}",
        extra={"field_key": field_key, "updated_fields": list(update_data.keys())},
    )

    return db_field


async def delete_rule_field(db: AsyncSession, field_key: str) -> None:
    """
    Delete a rule field.

    Args:
        db: Database session
        field_key: Field identifier

    Raises:
        NotFoundError: If field does not exist
        ConflictError: If field is in use (has versions in non-DRAFT status)
    """
    from app.repos import rule_field_version_repo

    field = await get_rule_field(db, field_key)

    # Check if there are any APPROVED or ACTIVE versions
    versions = await rule_field_version_repo.get_all_field_versions(db, field_key)
    for v in versions:
        if v.status in ("APPROVED", "ACTIVE"):
            raise ConflictError(
                f"Cannot delete field with {v.status} versions",
                details={"field_key": field_key, "status": v.status},
            )

    await db.delete(field)
    await db.flush()

    logger.info(f"Deleted rule field: {field_key}")


# ============================================================================
# RuleFieldMetadata Repository Functions
# ============================================================================


async def get_field_metadata(db: AsyncSession, field_key: str) -> list[RuleFieldMetadata]:
    """
    Retrieve all metadata entries for a specific field.

    Args:
        db: Database session
        field_key: Field identifier

    Returns:
        List of RuleFieldMetadata models

    Raises:
        NotFoundError: If field does not exist

    Example:
        metadata_list = get_field_metadata(db, "velocity_txn_count_10m_by_card")
    """
    # Verify field exists first
    await get_rule_field(db, field_key)

    stmt = (
        select(RuleFieldMetadata)
        .where(RuleFieldMetadata.field_key == field_key)
        .order_by(RuleFieldMetadata.meta_key)
    )

    result = await db.execute(stmt)
    metadata = result.scalars().all()

    logger.debug(
        f"Retrieved {len(metadata)} metadata entries for field: {field_key}",
        extra={"field_key": field_key, "count": len(metadata)},
    )

    return list(metadata)


async def get_specific_metadata(
    db: AsyncSession, field_key: str, meta_key: str
) -> RuleFieldMetadata:
    """
    Retrieve a specific metadata entry for a field.

    Args:
        db: Database session
        field_key: Field identifier
        meta_key: Metadata key

    Returns:
        RuleFieldMetadata model

    Raises:
        NotFoundError: If field or metadata does not exist

    Example:
        velocity_meta = get_specific_metadata(db, "velocity_txn_count_10m", "velocity")
    """
    # Verify field exists first
    await get_rule_field(db, field_key)

    stmt = select(RuleFieldMetadata).where(
        RuleFieldMetadata.field_key == field_key, RuleFieldMetadata.meta_key == meta_key
    )

    result = await db.execute(stmt)
    metadata = result.scalar_one_or_none()

    if not metadata:
        logger.warning(f"Metadata not found: {field_key}.{meta_key}")
        raise NotFoundError(
            f"Metadata '{meta_key}' not found for field '{field_key}'",
            details={"field_key": field_key, "meta_key": meta_key},
        )

    logger.debug(f"Retrieved metadata: {field_key}.{meta_key}")
    return metadata


async def upsert_field_metadata(
    db: AsyncSession, field_key: str, meta_key: str, meta_value: dict[str, Any]
) -> RuleFieldMetadata:
    """
    Create or update metadata for a field.

    If metadata with the given meta_key already exists, it's updated.
    Otherwise, a new metadata entry is created.

    Args:
        db: Database session
        field_key: Field identifier
        meta_key: Metadata key
        meta_value: JSONB metadata value

    Returns:
        Created or updated RuleFieldMetadata model

    Raises:
        NotFoundError: If field does not exist

    Example:
        velocity_config = {
            "aggregation": "COUNT",
            "window": {"value": 10, "unit": "MINUTES"}
        }
        metadata = upsert_field_metadata(db, "velocity_txn", "velocity", velocity_config)
    """
    # Verify field exists first
    await get_rule_field(db, field_key)

    # Try to find existing metadata
    stmt = select(RuleFieldMetadata).where(
        RuleFieldMetadata.field_key == field_key, RuleFieldMetadata.meta_key == meta_key
    )

    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing metadata
        existing.meta_value = meta_value
        await db.flush()
        logger.info(
            f"Updated metadata: {field_key}.{meta_key}",
            extra={"field_key": field_key, "meta_key": meta_key},
        )
        return existing
    else:
        # Create new metadata
        new_metadata = RuleFieldMetadata(
            field_key=field_key,
            meta_key=meta_key,
            meta_value=meta_value,
            created_at=datetime.now(UTC),
        )
        db.add(new_metadata)
        await db.flush()
        logger.info(
            f"Created metadata: {field_key}.{meta_key}",
            extra={"field_key": field_key, "meta_key": meta_key},
        )
        return new_metadata


async def delete_field_metadata(db: AsyncSession, field_key: str, meta_key: str) -> None:
    """
    Delete a specific metadata entry for a field.

    Args:
        db: Database session
        field_key: Field identifier
        meta_key: Metadata key to delete

    Raises:
        NotFoundError: If field or metadata does not exist

    Example:
        delete_field_metadata(db, "old_field", "deprecated_config")
    """
    # Get metadata (will raise NotFoundError if not exists)
    metadata = await get_specific_metadata(db, field_key, meta_key)

    await db.delete(metadata)
    await db.flush()

    logger.info(
        f"Deleted metadata: {field_key}.{meta_key}",
        extra={"field_key": field_key, "meta_key": meta_key},
    )
