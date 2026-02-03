"""Audit helper utilities.

This module provides helpers to:
1. Snapshot ORM entities into JSON-serializable dictionaries for `AuditLog.old_value`/`new_value`
2. Create audit log entries with a single function call

Supports both sync and async SQLAlchemy sessions.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.db.validators import to_jsonable


def snapshot_entity(
    entity: Any, *, include: Iterable[str] | None = None, exclude: Iterable[str] | None = None
) -> dict:
    """Snapshot an ORM entity into a JSON-serializable dict.

    By default, includes all mapped column attributes.

    Args:
        entity: SQLAlchemy ORM instance.
        include: Optional whitelist of field names.
        exclude: Optional blacklist of field names.

    Returns:
        Dict of field->value, JSON-serializable.
    """

    mapper = inspect(entity).mapper
    column_names = [attr.key for attr in mapper.column_attrs]

    if include is not None:
        include_set = set(include)
        column_names = [n for n in column_names if n in include_set]

    if exclude is not None:
        exclude_set = set(exclude)
        column_names = [n for n in column_names if n not in exclude_set]

    snap: dict[str, Any] = {}
    for name in column_names:
        snap[name] = to_jsonable(getattr(entity, name))

    return snap


def create_audit_log(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    performed_by: str,
) -> AuditLog:
    """Create and add an audit log entry to the database.

    Helper function to reduce boilerplate when creating audit logs.
    Automatically sets performed_at to current UTC time.

    Args:
        db: Database session
        entity_type: Type of entity (e.g., "RULE_VERSION", "RULESET")
        entity_id: ID of the entity
        action: Action performed (e.g., "SUBMIT", "APPROVE", "REJECT")
        old_value: Snapshot of entity before change
        new_value: Snapshot of entity after change
        performed_by: User ID who performed the action

    Returns:
        The created AuditLog instance (not yet flushed to database)
    """
    audit = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        performed_by=performed_by,
        performed_at=datetime.now(UTC),
    )
    db.add(audit)
    return audit


async def create_audit_log_async(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    performed_by: str,
) -> AuditLog:
    """Create and add an audit log entry to the database (async version).

    Helper function to reduce boilerplate when creating audit logs.
    Automatically sets performed_at to current UTC time.

    Args:
        db: Async database session
        entity_type: Type of entity (e.g., "RULE_VERSION", "RULESET")
        entity_id: ID of the entity
        action: Action performed (e.g., "SUBMIT", "APPROVE", "REJECT")
        old_value: Snapshot of entity before change
        new_value: Snapshot of entity after change
        performed_by: User ID who performed the action

    Returns:
        The created AuditLog instance (not yet flushed to database)
    """
    audit = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        performed_by=performed_by,
        performed_at=datetime.now(UTC),
    )
    db.add(audit)
    return audit
