"""
Repository layer for FieldRegistryManifest data access.

Provides database operations following the repository pattern.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.models import FieldRegistryManifest

logger = logging.getLogger(__name__)


# ============================================================================
# FieldRegistryManifest Repository Functions
# ============================================================================


async def get_latest_manifest(db: AsyncSession) -> FieldRegistryManifest | None:
    """
    Retrieve the latest field registry manifest.

    Args:
        db: Database session

    Returns:
        FieldRegistryManifest model or None if no manifest exists
    """
    stmt = (
        select(FieldRegistryManifest)
        .order_by(FieldRegistryManifest.registry_version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    manifest = result.scalar_one_or_none()

    if manifest:
        logger.debug(f"Retrieved latest manifest: v{manifest.registry_version}")
    else:
        logger.debug("No field registry manifest found")

    return manifest


async def get_manifest_by_version(db: AsyncSession, registry_version: int) -> FieldRegistryManifest:
    """
    Retrieve a field registry manifest by version number.

    Args:
        db: Database session
        registry_version: Registry version number

    Returns:
        FieldRegistryManifest model

    Raises:
        NotFoundError: If manifest does not exist
    """
    stmt = select(FieldRegistryManifest).where(
        FieldRegistryManifest.registry_version == registry_version
    )
    result = await db.execute(stmt)
    manifest = result.scalar_one_or_none()

    if not manifest:
        logger.warning(f"Field registry manifest not found: v{registry_version}")
        raise NotFoundError(
            f"Field registry manifest v{registry_version} not found",
            details={"registry_version": registry_version},
        )

    logger.debug(f"Retrieved field registry manifest: v{registry_version}")
    return manifest


async def list_manifests(db: AsyncSession, limit: int = 50) -> list[FieldRegistryManifest]:
    """
    Retrieve all field registry manifests, most recent first.

    Args:
        db: Database session
        limit: Maximum number of results

    Returns:
        List of FieldRegistryManifest models
    """
    stmt = (
        select(FieldRegistryManifest)
        .order_by(FieldRegistryManifest.registry_version.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    manifests = result.scalars().all()

    logger.info(f"Retrieved {len(manifests)} field registry manifests")
    return list(manifests)


async def create_manifest(
    db: AsyncSession,
    artifact_uri: str,
    checksum: str,
    field_count: int,
    created_by: str,
) -> FieldRegistryManifest:
    """
    Create a new field registry manifest.

    Args:
        db: Database session
        artifact_uri: S3 URI of the published artifact
        checksum: SHA-256 checksum (sha256:<hex>)
        field_count: Number of fields in the registry
        created_by: User who triggered the publish

    Returns:
        Created FieldRegistryManifest model

    Raises:
        ConflictError: If manifest creation fails
    """
    # Calculate next version number
    latest = await get_latest_manifest(db)
    next_version = (latest.registry_version if latest else 0) + 1

    manifest = FieldRegistryManifest(
        manifest_id=str(uuid.uuid7()),
        registry_version=next_version,
        artifact_uri=artifact_uri,
        checksum=checksum,
        field_count=field_count,
        created_at=datetime.now(UTC),
        created_by=created_by,
    )

    try:
        db.add(manifest)
        await db.flush()

        logger.info(
            f"Created field registry manifest: v{next_version}",
            extra={
                "registry_version": next_version,
                "artifact_uri": artifact_uri,
                "field_count": field_count,
            },
        )

        return manifest

    except IntegrityError:
        await db.rollback()
        logger.warning(f"Conflict creating field registry manifest: v{next_version}")
        raise ConflictError(
            f"Field registry manifest v{next_version} already exists",
            details={"registry_version": next_version},
        )


async def get_registry_version(db: AsyncSession) -> int:
    """
    Get the current field registry version.

    Args:
        db: Database session

    Returns:
        Current registry version (0 if no manifest exists)
    """
    manifest = await get_latest_manifest(db)
    return manifest.registry_version if manifest else 0
