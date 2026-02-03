from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApprovalResponse(BaseModel):
    approval_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    maker: str
    checker: str | None = None
    status: str
    remarks: str | None = None
    idempotency_key: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    rule_id: str | None = None
    ruleset_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AuditLogResponse(BaseModel):
    audit_id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    performed_by: str
    performed_at: datetime

    model_config = ConfigDict(from_attributes=True)
