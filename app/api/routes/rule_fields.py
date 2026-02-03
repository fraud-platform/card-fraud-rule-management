"""
FastAPI routes for RuleField and RuleFieldMetadata CRUD operations.

Provides endpoints for managing field metadata and their extensible configurations.
Permission-based authorization - endpoints require specific permissions.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.rule_field import (
    RuleFieldCreate,
    RuleFieldMetadataCreate,
    RuleFieldMetadataResponse,
    RuleFieldResponse,
    RuleFieldUpdate,
)
from app.core.dependencies import AsyncDbSession, CurrentUser
from app.core.errors import NotFoundError
from app.core.security import get_user_sub, require_permission
from app.db.models import AuditLog, RuleField, RuleFieldMetadata
from app.domain.enums import AuditEntityType
from app.repos import rule_field_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rule-fields", tags=["Rule Fields"])


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
    """
    Create an audit log entry for rule field operations.

    Args:
        db: Database session
        entity_type: Type of entity being audited
        entity_id: ID of the entity (field_key for rule fields)
        action: Action performed (CREATE, UPDATE, DELETE)
        old_value: Previous state (None for CREATE)
        new_value: New state (None for DELETE)
        performed_by: User who performed the action
    """
    # For RuleField, entity_id is the field_key (string)
    # We need to convert it to UUID for the audit log
    # Using a deterministic UUID based on the field_key
    if isinstance(entity_id, str):
        entity_id_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"rule_field:{entity_id}")
    else:
        entity_id_uuid = entity_id

    audit_entry = AuditLog(
        entity_type=entity_type.value,
        entity_id=str(entity_id_uuid),
        action=action,
        old_value=old_value,
        new_value=new_value,
        performed_by=performed_by,
    )
    db.add(audit_entry)


# ============================================================================
# RuleField Endpoints
# ============================================================================


@router.get(
    "",
    response_model=list[RuleFieldResponse],
    summary="List all rule fields",
    description="""
    Retrieve all rule fields ordered by field_id.

    Rule fields define the available dimensions that can be used in fraud rules.
    Examples: mcc, amount, merchant_id, velocity_txn_count_10m_by_card

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)
    """,
)
async def list_rule_fields(
    db: AsyncDbSession,
    user: CurrentUser,
) -> list[RuleField]:
    """List all rule fields."""
    fields = await rule_field_repo.get_all_rule_fields(db)

    logger.info(
        f"User {get_user_sub(user)} listed {len(fields)} rule fields",
        extra={"user": get_user_sub(user), "count": len(fields)},
    )

    return fields


@router.get(
    "/{field_key}",
    response_model=RuleFieldResponse,
    summary="Get a specific rule field",
    description="""
    Retrieve a single rule field by its unique key.

    **Path Parameters:**
    - `field_key`: Unique identifier for the field (e.g., "mcc", "amount")

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)

    **Errors:**
    - 404 Not Found: If the field_key does not exist
    """,
)
async def get_rule_field(
    field_key: Annotated[str, Path(description="Unique field identifier")],
    db: AsyncDbSession,
    user: CurrentUser,
) -> RuleField:
    """Get a specific rule field by key."""
    field = await rule_field_repo.get_rule_field(db, field_key)

    logger.info(
        f"User {get_user_sub(user)} retrieved rule field: {field_key}",
        extra={"user": get_user_sub(user), "field_key": field_key},
    )

    return field


@router.post(
    "",
    response_model=RuleFieldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new rule field",
    description="""
    Create a new rule field definition.

    Rule fields are the building blocks for fraud rules - they define what dimensions
    can be used in rule conditions.

    **Request Body:**
    - `field_key`: Unique identifier (lowercase, snake_case, immutable after creation)
    - `display_name`: Human-readable name
    - `data_type`: Data type (STRING, NUMBER, BOOLEAN, DATE, ENUM)
    - `allowed_operators`: List of permitted operators for this field
    - `multi_value_allowed`: Whether field can have multiple values
    - `is_sensitive`: Whether field contains PII/sensitive data
    - `is_active`: Whether field is currently usable in rules

    **Authentication:**
    - Requires valid JWT token with `rule_field:create` permission

    **Errors:**
    - 409 Conflict: If field_key already exists
    - 403 Forbidden: If user lacks required permission

    **Audit:**
    - Creates audit log entry with action=CREATE
    """,
)
async def create_rule_field(
    field: RuleFieldCreate,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("rule_field:create"))],
) -> RuleField:
    """Create a new rule field (Admin only)."""
    new_field = await rule_field_repo.create_rule_field(db, field, get_user_sub(user))

    # Audit logging
    await log_audit(
        db=db,
        entity_type=AuditEntityType.RULE_FIELD,
        entity_id=new_field.field_key,
        action="CREATE",
        old_value=None,
        new_value={
            "field_key": new_field.field_key,
            "field_id": new_field.field_id,
            "display_name": new_field.display_name,
            "description": new_field.description,
            "data_type": new_field.data_type,
            "allowed_operators": new_field.allowed_operators,
            "multi_value_allowed": new_field.multi_value_allowed,
            "is_sensitive": new_field.is_sensitive,
        },
        performed_by=get_user_sub(user),
    )

    await db.commit()

    logger.info(
        f"User {get_user_sub(user)} created rule field: {new_field.field_key}",
        extra={
            "user": get_user_sub(user),
            "field_key": new_field.field_key,
            "data_type": new_field.data_type,
        },
    )

    return new_field


@router.patch(
    "/{field_key}",
    response_model=RuleFieldResponse,
    summary="Update a rule field",
    description="""
    Partially update an existing rule field.

    Only the provided fields will be updated; omitted fields remain unchanged.
    The `field_key` is immutable and cannot be changed.

    **Path Parameters:**
    - `field_key`: Unique identifier of the field to update

    **Request Body:**
    - All fields are optional (partial update)
    - Commonly updated: `is_active`, `display_name`, `allowed_operators`

    **Authentication:**
    - Requires valid JWT token with `rule_field:update` permission

    **Errors:**
    - 404 Not Found: If field_key does not exist
    - 403 Forbidden: If user lacks required permission

    **Audit:**
    - Creates audit log entry with action=UPDATE and before/after state
    """,
)
async def update_rule_field(
    field_key: Annotated[str, Path(description="Unique field identifier")],
    updates: RuleFieldUpdate,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("rule_field:update"))],
) -> RuleField:
    """Update a rule field (Admin only, partial updates)."""
    # Capture old state for audit
    old_field = await rule_field_repo.get_rule_field(db, field_key)
    old_value = {
        "field_key": old_field.field_key,
        "field_id": old_field.field_id,
        "display_name": old_field.display_name,
        "description": old_field.description,
        "data_type": old_field.data_type,
        "allowed_operators": old_field.allowed_operators,
        "multi_value_allowed": old_field.multi_value_allowed,
        "is_sensitive": old_field.is_sensitive,
    }

    # Perform update
    updated_field = await rule_field_repo.update_rule_field(db, field_key, updates)

    # Capture new state for audit
    new_value = {
        "field_key": updated_field.field_key,
        "field_id": updated_field.field_id,
        "display_name": updated_field.display_name,
        "description": updated_field.description,
        "data_type": updated_field.data_type,
        "allowed_operators": updated_field.allowed_operators,
        "multi_value_allowed": updated_field.multi_value_allowed,
        "is_sensitive": updated_field.is_sensitive,
    }

    # Audit logging
    await log_audit(
        db=db,
        entity_type=AuditEntityType.RULE_FIELD,
        entity_id=updated_field.field_key,
        action="UPDATE",
        old_value=old_value,
        new_value=new_value,
        performed_by=get_user_sub(user),
    )

    await db.commit()

    logger.info(
        f"User {get_user_sub(user)} updated rule field: {field_key}",
        extra={"user": get_user_sub(user), "field_key": field_key},
    )

    return updated_field


# ============================================================================
# RuleField Metadata Endpoints
# ============================================================================


@router.get(
    "/{field_key}/metadata",
    response_model=list[RuleFieldMetadataResponse],
    summary="Get all metadata for a field",
    description="""
    Retrieve all metadata entries for a specific rule field.

    Metadata provides extensible configuration for fields, such as:
    - Velocity field configurations (aggregation, window, group_by)
    - UI display settings (group, order)
    - Validation rules (enum_values, min/max, regex)

    **Path Parameters:**
    - `field_key`: Unique identifier of the field

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)

    **Errors:**
    - 404 Not Found: If field_key does not exist
    """,
)
async def get_field_metadata(
    field_key: Annotated[str, Path(description="Unique field identifier")],
    db: AsyncDbSession,
    user: CurrentUser,
) -> list[RuleFieldMetadata]:
    """Get all metadata entries for a field."""
    metadata_list = await rule_field_repo.get_field_metadata(db, field_key)

    logger.info(
        f"User {get_user_sub(user)} retrieved {len(metadata_list)} metadata "
        f"entries for field: {field_key}",
        extra={"user": get_user_sub(user), "field_key": field_key, "count": len(metadata_list)},
    )

    return metadata_list


@router.get(
    "/{field_key}/metadata/{meta_key}",
    response_model=RuleFieldMetadataResponse,
    summary="Get specific metadata entry",
    description="""
    Retrieve a specific metadata entry for a field.

    **Path Parameters:**
    - `field_key`: Unique identifier of the field
    - `meta_key`: Metadata key (e.g., "velocity", "ui_config", "validation")

    **Authentication:**
    - Requires valid JWT token
    - No specific role required (authenticated users can read)

    **Errors:**
    - 404 Not Found: If field_key or meta_key does not exist
    """,
)
async def get_specific_metadata(
    field_key: Annotated[str, Path(description="Unique field identifier")],
    meta_key: Annotated[str, Path(description="Metadata key")],
    db: AsyncDbSession,
    user: CurrentUser,
) -> RuleFieldMetadata:
    """Get a specific metadata entry for a field."""
    metadata = await rule_field_repo.get_specific_metadata(db, field_key, meta_key)

    logger.info(
        f"User {get_user_sub(user)} retrieved metadata: {field_key}.{meta_key}",
        extra={"user": get_user_sub(user), "field_key": field_key, "meta_key": meta_key},
    )

    return metadata


@router.put(
    "/{field_key}/metadata/{meta_key}",
    response_model=RuleFieldMetadataResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update metadata",
    description="""
    Create or update a metadata entry for a field (upsert operation).

    If metadata with the given meta_key already exists, it will be updated.
    Otherwise, a new metadata entry will be created.

    **Path Parameters:**
    - `field_key`: Unique identifier of the field
    - `meta_key`: Metadata key (e.g., "velocity", "ui_config")

    **Request Body:**
    - `meta_value`: JSONB object containing the metadata configuration

    **Authentication:**
    - Requires valid JWT token with `rule_field:update` permission

    **Errors:**
    - 404 Not Found: If field_key does not exist
    - 403 Forbidden: If user lacks required permission

    **Audit:**
    - Creates audit log entry with action=CREATE or UPDATE

    **Example:**
    ```json
    {
      "meta_value": {
        "aggregation": "COUNT",
        "metric": "txn",
        "window": {"value": 10, "unit": "MINUTES"},
        "group_by": ["CARD"]
      }
    }
    ```
    """,
)
async def upsert_metadata(
    field_key: Annotated[str, Path(description="Unique field identifier")],
    meta_key: Annotated[str, Path(description="Metadata key")],
    metadata: RuleFieldMetadataCreate,
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("rule_field:update"))],
) -> RuleFieldMetadata:
    """Create or update metadata for a field (Admin only)."""
    # Check if metadata already exists (for audit logging)
    try:
        existing = await rule_field_repo.get_specific_metadata(db, field_key, meta_key)
        old_value = {
            "field_key": existing.field_key,
            "meta_key": existing.meta_key,
            "meta_value": existing.meta_value,
        }
        action = "UPDATE"
    except NotFoundError:
        old_value = None
        action = "CREATE"

    # Perform upsert
    result = await rule_field_repo.upsert_field_metadata(
        db, field_key, meta_key, metadata.meta_value
    )

    # Audit logging
    await log_audit(
        db=db,
        entity_type=AuditEntityType.RULE_FIELD_METADATA,
        entity_id=f"{field_key}:{meta_key}",
        action=action,
        old_value=old_value,
        new_value={
            "field_key": result.field_key,
            "meta_key": result.meta_key,
            "meta_value": result.meta_value,
        },
        performed_by=get_user_sub(user),
    )

    await db.commit()

    logger.info(
        f"User {get_user_sub(user)} {action.lower()}d metadata: {field_key}.{meta_key}",
        extra={
            "user": get_user_sub(user),
            "field_key": field_key,
            "meta_key": meta_key,
            "action": action,
        },
    )

    return result


@router.delete(
    "/{field_key}/metadata/{meta_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete metadata entry",
    description="""
    Delete a specific metadata entry for a field.

    **Path Parameters:**
    - `field_key`: Unique identifier of the field
    - `meta_key`: Metadata key to delete

    **Authentication:**
    - Requires valid JWT token with `rule_field:delete` permission

    **Errors:**
    - 404 Not Found: If field_key or meta_key does not exist
    - 403 Forbidden: If user lacks required permission

    **Audit:**
    - Creates audit log entry with action=DELETE and old state

    **Response:**
    - 204 No Content on success
    """,
)
async def delete_metadata(
    field_key: Annotated[str, Path(description="Unique field identifier")],
    meta_key: Annotated[str, Path(description="Metadata key")],
    db: AsyncDbSession,
    user: Annotated[dict[str, Any], Depends(require_permission("rule_field:delete"))],
) -> None:
    """Delete a metadata entry (Admin only)."""
    # Capture old state for audit
    existing = await rule_field_repo.get_specific_metadata(db, field_key, meta_key)
    old_value = {
        "field_key": existing.field_key,
        "meta_key": existing.meta_key,
        "meta_value": existing.meta_value,
    }

    # Perform deletion
    await rule_field_repo.delete_field_metadata(db, field_key, meta_key)

    # Audit logging
    await log_audit(
        db=db,
        entity_type=AuditEntityType.RULE_FIELD_METADATA,
        entity_id=f"{field_key}:{meta_key}",
        action="DELETE",
        old_value=old_value,
        new_value=None,
        performed_by=get_user_sub(user),
    )

    await db.commit()

    logger.info(
        f"User {get_user_sub(user)} deleted metadata: {field_key}.{meta_key}",
        extra={"user": get_user_sub(user), "field_key": field_key, "meta_key": meta_key},
    )
