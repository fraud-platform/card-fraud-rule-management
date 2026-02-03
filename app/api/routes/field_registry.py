"""
FastAPI routes for Field Registry management.

Provides endpoints for managing the field registry versioning and publishing.
Permission-based authorization - endpoints require specific permissions.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.rule_field import FieldRegistryManifestResponse
from app.core.dependencies import AsyncDbSession, CurrentUser
from app.core.security import get_user_sub, require_permission
from app.db.models import AuditLog
from app.domain.enums import AuditEntityType
from app.repos import field_registry_manifest_repo, rule_field_repo, rule_field_version_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/field-registry", tags=["Field Registry"])


# ============================================================================
# Audit Logging Helper
# ============================================================================


async def log_audit(
    db: AsyncSession,
    entity_type: AuditEntityType,
    entity_id: uuid.UUID | str,
    action: str,
    old_value: dict | None,
    new_value: dict | None,
    performed_by: str,
) -> None:
    """Create an audit log entry for field registry operations."""
    audit_entry = AuditLog(
        entity_type=entity_type.value,
        entity_id=str(entity_id),
        action=action,
        old_value=old_value,
        new_value=new_value,
        performed_by=performed_by,
    )
    db.add(audit_entry)


# ============================================================================
# Field Registry Endpoints
# =============================================================================


@router.get(
    "",
    response_model=dict,
    summary="Get active field registry info",
    description="""
    Retrieve information about the active field registry.

    Returns the latest manifest and field count.

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)
    """,
)
async def get_active_registry(
    db: AsyncDbSession,
    user: CurrentUser,
) -> dict:
    """Get active field registry information."""
    manifest = await field_registry_manifest_repo.get_latest_manifest(db)

    if manifest:
        return {
            "registry_version": manifest.registry_version,
            "artifact_uri": manifest.artifact_uri,
            "checksum": manifest.checksum,
            "field_count": manifest.field_count,
            "created_at": manifest.created_at,
            "created_by": manifest.created_by,
        }
    else:
        return {
            "registry_version": 0,
            "artifact_uri": None,
            "checksum": None,
            "field_count": 0,
            "created_at": None,
            "created_by": None,
        }


@router.get(
    "/versions",
    response_model=list[FieldRegistryManifestResponse],
    summary="List published field registry versions",
    description="""
    Retrieve all published field registry versions.

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)
    """,
)
async def list_registry_versions(
    db: AsyncDbSession,
    user: CurrentUser,
) -> list:
    """List all field registry versions."""
    manifests = await field_registry_manifest_repo.list_manifests(db, limit=100)
    return manifests


@router.get(
    "/versions/{registry_version}",
    response_model=FieldRegistryManifestResponse,
    summary="Get specific registry version",
    description="""
    Retrieve a specific field registry manifest by version number.

    **Path Parameters:**
    - `registry_version`: Registry version number

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)

    **Errors:**
    - 404 Not Found: If registry version does not exist
    """,
)
async def get_registry_version(
    registry_version: Annotated[int, Path(description="Registry version number")],
    db: AsyncDbSession,
    user: CurrentUser,
) -> FieldRegistryManifestResponse:
    """Get specific field registry version."""
    manifest = await field_registry_manifest_repo.get_manifest_by_version(db, registry_version)
    return manifest


@router.get(
    "/versions/{registry_version}/fields",
    response_model=list[dict],
    summary="Get fields in a registry version",
    description="""
    Retrieve all fields that were part of a specific registry version.

    **Path Parameters:**
    - `registry_version`: Registry version number

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)
    """,
)
async def get_registry_version_fields(
    registry_version: Annotated[int, Path(description="Registry version number")],
    db: AsyncDbSession,
    user: CurrentUser,
) -> list:
    """Get all fields from a specific registry version."""
    # For now, return all APPROVED versions
    # In production, this would query the S3 artifact or use a snapshot table
    versions = await rule_field_version_repo.get_all_approved_versions(db)

    return [
        {
            "field_key": v.field_key,
            "field_id": v.field_id,
            "display_name": v.display_name,
            "description": v.description,
            "data_type": v.data_type,
            "allowed_operators": v.allowed_operators,
            "multi_value_allowed": v.multi_value_allowed,
            "is_sensitive": v.is_sensitive,
        }
        for v in versions
    ]


@router.get(
    "/next-field-id",
    response_model=dict,
    summary="Get next available field_id",
    description="""
    Get the next available field_id for creating new fields.

    Standard fields use IDs 1-26. New custom fields start from 27.

    **Authentication:**
    - Requires valid JWT token
    - Requires `rule_field:create` permission
    """,
)
async def get_next_field_id(
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("rule_field:create"))],
) -> dict:
    """Get next available field_id."""
    next_id = await rule_field_repo.get_next_field_id(db)
    return {"next_field_id": next_id}


@router.post(
    "/publish",
    response_model=FieldRegistryManifestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish field registry",
    description="""
    Manually publish a new field registry version.

    Compiles all APPROVED field versions into a JSON artifact
    and publishes to S3-compatible storage.

    **Authentication:**
    - Requires valid JWT token
    - Requires `rule_field:create` permission

    **Audit:**
    - Creates audit log entry with action=PUBLISH
    """,
)
async def publish_registry(
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("rule_field:create"))],
) -> dict:
    """Publish field registry to S3."""
    from app.services.field_registry_publisher import FieldRegistryPublisher

    publisher = FieldRegistryPublisher()

    # Compile registry from APPROVED versions
    artifact = await publisher.compile_registry(db)

    # Publish to S3 (or filesystem)
    manifest = await publisher.publish(db, artifact, get_user_sub(user))

    # Audit logging
    log_audit(
        db=db,
        entity_type=AuditEntityType.FIELD_REGISTRY_MANIFEST,
        entity_id=manifest.manifest_id,
        action="PUBLISH",
        old_value=None,
        new_value={
            "registry_version": manifest.registry_version,
            "artifact_uri": manifest.artifact_uri,
            "field_count": manifest.field_count,
        },
        performed_by=get_user_sub(user),
    )
    await db.commit()

    logger.info(
        f"User {get_user_sub(user)} published field registry v{manifest.registry_version}",
        extra={"user": get_user_sub(user), "registry_version": manifest.registry_version},
    )

    return manifest
