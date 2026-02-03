"""
SQLAlchemy 2.x ORM models for the Fraud Governance API.

All models map to existing tables in the 'fraud_gov' schema.
Models use the Mapped[] type annotation syntax and mapped_column.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from app.db.validators import validate_json_payload, validate_uuid_string
from app.domain.enums import (
    ApprovalAction,
    ApprovalEntityType,
    ApprovalStatus,
    AuditEntityType,
    DataType,
    EntityStatus,
    RuleType,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    # The production database objects live in this dedicated schema.
    metadata = MetaData(schema="fraud_gov")


class RuleField(Base):
    """
    Field definitions for rule conditions (identity table).

    field_id maps to engine FieldRegistry for O(1) lookup.
    Versioning tracked in rule_field_versions table.
    """

    __tablename__ = "rule_fields"
    __table_args__ = (
        CheckConstraint(
            "data_type IN ('STRING','NUMBER','BOOLEAN','DATE','ENUM')",
            name="chk_rule_fields_data_type",
        ),
    )

    field_key: Mapped[str] = mapped_column(Text, primary_key=True)
    field_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str] = mapped_column(
        Enum(DataType, create_constraint=True, name="data_type"), nullable=False
    )
    allowed_operators: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        comment="PostgreSQL TEXT[] array for storing allowed operator names",
    )
    multi_value_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Optimistic locking version - increments on each update",
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.now(UTC),
        onupdate=datetime.now(UTC),
    )

    # Relationships
    field_metadata: Mapped[list[RuleFieldMetadata]] = relationship(
        "RuleFieldMetadata", back_populates="field", cascade="all, delete-orphan"
    )
    versions: Mapped[list[RuleFieldVersion]] = relationship(
        "RuleFieldVersion", back_populates="field", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RuleField(field_key={self.field_key}, field_id={self.field_id}, data_type={self.data_type})>"


class RuleFieldMetadata(Base):
    """
    Extensible metadata for rule fields (e.g., enum_values, min/max, regex).

    Stores additional configuration as key-value pairs in JSONB format.
    """

    __tablename__ = "rule_field_metadata"
    __table_args__ = (
        CheckConstraint("length(meta_key) > 0", name="chk_rule_field_metadata_meta_key"),
    )

    field_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("fraud_gov.rule_fields.field_key", ondelete="CASCADE"),
        primary_key=True,
    )
    meta_key: Mapped[str] = mapped_column(Text, primary_key=True)
    meta_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )

    # Relationships
    field: Mapped[RuleField] = relationship("RuleField", back_populates="field_metadata")

    def __repr__(self) -> str:
        return f"<RuleFieldMetadata(field_key={self.field_key}, meta_key={self.meta_key})>"


class RuleFieldVersion(Base):
    """
    Immutable version of a field definition.

    Governance layer for approvals and audit. Runtime consumes from S3.
    Each version goes through maker-checker workflow independently.
    """

    __tablename__ = "rule_field_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED')",
            name="chk_rule_field_versions_status",
        ),
        CheckConstraint(
            "(status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL) OR status <> 'APPROVED'",
            name="chk_rule_field_versions_approved_fields",
        ),
    )

    rule_field_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    field_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("fraud_gov.rule_fields.field_key", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    field_id: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str] = mapped_column(
        Enum(DataType, create_constraint=True, name="data_type"), nullable=False
    )
    allowed_operators: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    multi_value_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        Enum(EntityStatus, create_constraint=True, name="entity_status"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Relationships
    field: Mapped[RuleField] = relationship("RuleField", back_populates="versions")

    def __repr__(self) -> str:
        return f"<RuleFieldVersion(rule_field_version_id={self.rule_field_version_id}, field_key={self.field_key}, version={self.version}, status={self.status})>"


class Rule(Base):
    """
    Logical identity of a fraud rule.

    Tracks the current version and overall status. The actual rule logic
    is stored in RuleVersion (immutable versions).

    Optimistic Locking:
    - The 'version' column is incremented on every update
    - Updates must include the expected version in WHERE clause
    - ConflictError is raised if version doesn't match (concurrent modification)
    """

    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED')",
            name="chk_rules_status",
        ),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(
        Enum(RuleType, create_constraint=True, name="rule_type"), nullable=False
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(EntityStatus, create_constraint=True, name="entity_status"), nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Optimistic locking version - increments on each update",
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.now(UTC),
        onupdate=datetime.now(UTC),
    )

    # Relationships
    versions: Mapped[list[RuleVersion]] = relationship(
        "RuleVersion", back_populates="rule", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Rule(rule_id={self.rule_id}, name={self.rule_name}, status={self.status})>"

    @validates("rule_id")
    def _validate_rule_id(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)


class RuleVersion(Base):
    """
    Immutable version of a rule with condition tree, priority, and scope.

    Once approved, the condition_tree cannot be modified.
    Each version goes through maker-checker workflow independently.
    """

    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version", name="rule_versions_rule_id_version_key"),
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUPERSEDED')",
            name="chk_rule_versions_status",
        ),
        CheckConstraint(
            """
            (status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
            OR
            (status <> 'APPROVED')
            """,
            name="chk_rule_versions_approved_fields",
        ),
        CheckConstraint(
            "priority BETWEEN 1 AND 1000",
            name="chk_rule_versions_priority_range",
        ),
        CheckConstraint(
            "action IN ('APPROVE','DECLINE','REVIEW')",
            name="chk_rule_versions_action",
        ),
    )

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fraud_gov.rules.rule_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    condition_tree: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="REVIEW",
        comment="Action when rule matches: APPROVE, DECLINE, or REVIEW (must match runtime Decision.java)",
    )
    scope: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment='Scope dimensions for this rule version (e.g., {"network": ["VISA"], "mcc": ["7995"]})',
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(EntityStatus, create_constraint=True, name="entity_status"), nullable=False
    )

    # Relationships
    rule: Mapped[Rule] = relationship("Rule", back_populates="versions")
    ruleset_memberships: Mapped[list[RuleSetVersionRule]] = relationship(
        "RuleSetVersionRule", back_populates="rule_version"
    )

    def __repr__(self) -> str:
        return f"<RuleVersion(rule_version_id={self.rule_version_id}, version={self.version}, status={self.status})>"

    @property
    def rule_name(self) -> str:
        """Get rule name from parent Rule relationship."""
        return self.rule.rule_name if self.rule else ""

    @property
    def rule_type(self) -> str:
        """Get rule type from parent Rule relationship."""
        return self.rule.rule_type if self.rule else ""

    @validates("rule_version_id", "rule_id")
    def _validate_ids(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)


class RuleSet(Base):
    """
    Ruleset identity - immutable metadata.

    This table defines WHAT the ruleset is, not which snapshot.
    One row per unique (environment, region, country, rule_type) combination.
    """

    __tablename__ = "rulesets"
    __table_args__ = (UniqueConstraint("environment", "region", "country", "rule_type"),)

    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(
        Enum(RuleType, create_constraint=True, name="rule_type"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=datetime.now(UTC),
        onupdate=datetime.now(UTC),
    )

    # Relationships
    versions: Mapped[list[RuleSetVersion]] = relationship(
        "RuleSetVersion", back_populates="ruleset", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<RuleSet(ruleset_id={self.ruleset_id}, "
            f"environment={self.environment}, region={self.region}, "
            f"country={self.country}, rule_type={self.rule_type})>"
        )

    @validates("ruleset_id")
    def _validate_ruleset_id(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)


class RuleSetVersion(Base):
    """
    Immutable snapshot of a ruleset.

    This is what runtime & transaction-management reference.
    No rule drift possible, no partial updates.
    Runtime consumes compiled artifacts from S3, not from this table.
    """

    __tablename__ = "ruleset_versions"
    __table_args__ = (
        UniqueConstraint("ruleset_id", "version", name="ruleset_versions_ruleset_id_version_key"),
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','APPROVED','ACTIVE','SUPERSEDED')",
            name="chk_ruleset_versions_status",
        ),
        CheckConstraint(
            """
            (status IN ('APPROVED','ACTIVE') AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
            OR
            (status NOT IN ('APPROVED','ACTIVE'))
            """,
            name="chk_ruleset_versions_approved_fields",
        ),
        CheckConstraint(
            """
            (status = 'ACTIVE' AND activated_at IS NOT NULL)
            OR
            (status <> 'ACTIVE')
            """,
            name="chk_ruleset_versions_activated",
        ),
    )

    ruleset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fraud_gov.rulesets.ruleset_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(EntityStatus, create_constraint=True, name="entity_status"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Relationships
    ruleset: Mapped[RuleSet] = relationship("RuleSet", back_populates="versions")
    rule_memberships: Mapped[list[RuleSetVersionRule]] = relationship(
        "RuleSetVersionRule", back_populates="ruleset_version", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<RuleSetVersion(ruleset_version_id={self.ruleset_version_id}, "
            f"ruleset_id={self.ruleset_id}, version={self.version}, status={self.status})>"
        )

    @validates("ruleset_version_id", "ruleset_id")
    def _validate_ids(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)


class RuleSetVersionRule(Base):
    """
    Join table linking RuleSetVersion to RuleVersion.

    Membership is snapshot-bound - no rule drift possible.
    """

    __tablename__ = "ruleset_version_rules"
    __table_args__ = {}

    ruleset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fraud_gov.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        primary_key=True,
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fraud_gov.rule_versions.rule_version_id"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )

    # Relationships
    ruleset_version: Mapped[RuleSetVersion] = relationship(
        "RuleSetVersion", back_populates="rule_memberships"
    )
    rule_version: Mapped[RuleVersion] = relationship(
        "RuleVersion", back_populates="ruleset_memberships"
    )

    def __repr__(self) -> str:
        return (
            f"<RuleSetVersionRule(ruleset_version_id={self.ruleset_version_id}, "
            f"rule_version_id={self.rule_version_id})>"
        )

    @validates("ruleset_version_id", "rule_version_id")
    def _validate_ids(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)


class Approval(Base):
    """
    Maker-checker workflow tracking for rule versions and rulesets.

    Enforces separation of duties: maker cannot be checker.
    Supports idempotent submit operations via idempotency_key.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("action IN ('SUBMIT','APPROVE','REJECT')", name="chk_approvals_action"),
        CheckConstraint("checker IS NULL OR maker <> checker", name="chk_approvals_maker_checker"),
    )

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    entity_type: Mapped[str] = mapped_column(
        Enum(ApprovalEntityType, create_constraint=True, name="approval_entity_type"),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=False), nullable=False)
    action: Mapped[str] = mapped_column(
        Enum(ApprovalAction, create_constraint=True, name="approval_action"), nullable=False
    )
    maker: Mapped[str] = mapped_column(Text, nullable=False)
    checker: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(ApprovalStatus, create_constraint=True, name="approval_status"), nullable=False
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    @validates("approval_id", "entity_id")
    def _validate_ids(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)

    def __repr__(self) -> str:
        return f"<Approval(approval_id={self.approval_id}, entity_type={self.entity_type}, status={self.status})>"


class AuditLog(Base):
    """
    Append-only audit trail for all entity changes.

    Captures before/after state for compliance and debugging.
    """

    __tablename__ = "audit_log"
    __table_args__ = {}

    # Use Uuid type for psycopg v3 compatibility (stores as string)
    audit_id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid7()))
    entity_type: Mapped[str] = mapped_column(
        Enum(AuditEntityType, create_constraint=True, name="audit_entity_type"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    performed_by: Mapped[str] = mapped_column(Text, nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )

    @validates("audit_id", "entity_id")
    def _validate_ids(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)

    @validates("old_value", "new_value")
    def _validate_json_payload(self, key: str, value: Any) -> Any:
        return validate_json_payload(key, value)

    def __repr__(self) -> str:
        return f"<AuditLog(audit_id={self.audit_id}, entity_type={self.entity_type}, action={self.action})>"


class RuleSetManifest(Base):
    """
    Published ruleset artifact manifest.

    Tracks ruleset artifacts published to S3-compatible storage.
    Each row represents a published artifact with its URI, checksum, and metadata.

    The ruleset_key identifies the runtime publication boundary:
    - CARD_AUTH: Authorization decisioning rules (FIRST_MATCH)
    - CARD_MONITORING: Post-authorization analytics rules (ALL_MATCHING)

    Version is monotonically increasing per (environment, ruleset_key) combination.
    """

    __tablename__ = "ruleset_manifest"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('ALLOWLIST','BLOCKLIST','AUTH','MONITORING')",
            name="chk_ruleset_manifest_rule_type",
        ),
        CheckConstraint("ruleset_version >= 1", name="chk_ruleset_manifest_ruleset_version"),
        CheckConstraint("length(checksum) = 71", name="chk_ruleset_manifest_checksum_len"),
    )

    ruleset_manifest_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    environment: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(
        Enum(RuleType, create_constraint=True, name="rule_type"), nullable=False
    )
    ruleset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("fraud_gov.ruleset_versions.ruleset_version_id"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_registry_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<RuleSetManifest(ruleset_manifest_id={self.ruleset_manifest_id}, "
            f"environment={self.environment}, region={self.region}, "
            f"country={self.country}, rule_type={self.rule_type}, "
            f"version={self.ruleset_version})>"
        )

    @validates("ruleset_manifest_id", "ruleset_version_id")
    def _validate_id(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)


class FieldRegistryManifest(Base):
    """
    Published field registry artifact manifest.

    Tracks field registry artifacts published to S3-compatible storage.
    Each row represents a published artifact with its URI, checksum, and metadata.
    """

    __tablename__ = "field_registry_manifest"
    __table_args__ = (
        CheckConstraint("length(checksum) = 71", name="chk_field_registry_manifest_checksum_len"),
    )

    manifest_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid7())
    )
    registry_version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=datetime.now(UTC)
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<FieldRegistryManifest(manifest_id={self.manifest_id}, "
            f"registry_version={self.registry_version}, "
            f"field_count={self.field_count})>"
        )

    @validates("manifest_id")
    def _validate_id(self, key: str, value: uuid.UUID | str) -> str:
        return validate_uuid_string(key, value)
