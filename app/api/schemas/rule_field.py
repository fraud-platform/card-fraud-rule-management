"""
Pydantic schemas for RuleField and RuleFieldMetadata API operations.

These schemas define the request/response structure for the RuleField CRUD endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import DataType, Operator

# ============================================================================
# RuleField Schemas
# ============================================================================


class RuleFieldBase(BaseModel):
    """Base schema with fields common to all RuleField operations."""

    display_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable name for the field",
        examples=["Merchant Category Code"],
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Detailed description of the field",
        examples=["Merchant category code for transaction classification"],
    )
    data_type: DataType = Field(
        ...,
        description="Data type of the field (STRING, NUMBER, BOOLEAN, DATE, ENUM)",
        examples=[DataType.STRING],
    )
    allowed_operators: list[Operator] = Field(
        ...,
        min_length=1,
        description="List of operators allowed for this field",
        examples=[[Operator.EQ, Operator.IN]],
    )
    multi_value_allowed: bool = Field(
        default=False,
        description="Whether the field can have multiple values",
        examples=[False],
    )
    is_sensitive: bool = Field(
        default=False,
        description="Whether the field contains sensitive data (PII, etc.)",
        examples=[False],
    )

    @field_validator("allowed_operators")
    @classmethod
    def validate_operators_not_empty(cls, v: list[Operator]) -> list[Operator]:
        """Ensure at least one operator is provided."""
        if not v:
            raise ValueError("At least one operator must be specified")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "display_name": "Merchant Category Code",
                    "description": "Merchant category code",
                    "data_type": "STRING",
                    "allowed_operators": ["EQ", "IN"],
                    "multi_value_allowed": True,
                    "is_sensitive": False,
                }
            ]
        }
    }


class RuleFieldCreate(RuleFieldBase):
    """Schema for creating a new RuleField."""

    field_key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern="^[a-z][a-z0-9_]*$",
        description="Unique identifier for the field (lowercase, alphanumeric, underscores only)",
        examples=["mcc"],
    )

    @field_validator("field_key")
    @classmethod
    def validate_field_key_format(cls, v: str) -> str:
        """Ensure field_key follows snake_case convention."""
        if not v.islower():
            raise ValueError("field_key must be lowercase")
        if "__" in v:
            raise ValueError("field_key cannot contain consecutive underscores")
        if v.startswith("_") or v.endswith("_"):
            raise ValueError("field_key cannot start or end with underscore")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "field_key": "mcc",
                    "display_name": "Merchant Category Code",
                    "description": "Merchant category code",
                    "data_type": "STRING",
                    "allowed_operators": ["EQ", "IN"],
                    "multi_value_allowed": True,
                    "is_sensitive": False,
                }
            ]
        }
    }


class RuleFieldUpdate(BaseModel):
    """
    Schema for updating an existing RuleField.

    All fields are optional to support partial updates.
    field_key and field_id are immutable and cannot be updated.
    """

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Human-readable name for the field",
        examples=["Updated Display Name"],
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Detailed description of the field",
    )
    data_type: DataType | None = Field(
        default=None,
        description="Data type of the field",
        examples=[DataType.NUMBER],
    )
    allowed_operators: list[Operator] | None = Field(
        default=None,
        min_length=1,
        description="List of operators allowed for this field",
        examples=[[Operator.GT, Operator.LT]],
    )
    multi_value_allowed: bool | None = Field(
        default=None,
        description="Whether the field can have multiple values",
        examples=[True],
    )
    is_sensitive: bool | None = Field(
        default=None,
        description="Whether the field contains sensitive data",
        examples=[True],
    )

    @field_validator("allowed_operators")
    @classmethod
    def validate_operators_not_empty(cls, v: list[Operator] | None) -> list[Operator] | None:
        """Ensure at least one operator is provided if field is being updated."""
        if v is not None and not v:
            raise ValueError("At least one operator must be specified")
        return v


class RuleFieldResponse(RuleFieldBase):
    """Schema for RuleField responses (GET endpoints)."""

    field_key: str = Field(
        ...,
        description="Unique identifier for the field",
        examples=["mcc"],
    )
    field_id: int = Field(
        ...,
        description="Integer ID matching engine FieldRegistry",
        examples=[1],
    )
    current_version: int = Field(
        ...,
        description="Latest version number",
        examples=[1],
    )
    version: int = Field(
        ...,
        description="Optimistic locking version",
        examples=[1],
    )
    created_by: str = Field(
        ...,
        description="User who created the field",
        examples=["user@example.com"],
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the field was created",
    )
    updated_at: datetime = Field(
        ...,
        description="Timestamp when the field was last updated",
    )

    model_config = {
        "from_attributes": True,  # Enable ORM mode for SQLAlchemy models
        "json_schema_extra": {
            "examples": [
                {
                    "field_key": "mcc",
                    "field_id": 7,
                    "display_name": "MCC",
                    "description": "Merchant category code",
                    "data_type": "STRING",
                    "allowed_operators": ["EQ", "IN"],
                    "multi_value_allowed": True,
                    "is_sensitive": False,
                    "current_version": 1,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2026-01-01T12:00:00Z",
                    "updated_at": "2026-01-01T12:00:00Z",
                }
            ]
        },
    }


# ============================================================================
# RuleFieldVersion Schemas
# ============================================================================


class RuleFieldVersionResponse(BaseModel):
    """Schema for RuleFieldVersion responses."""

    rule_field_version_id: str = Field(
        ...,
        description="Unique identifier for the field version",
    )
    field_key: str = Field(
        ...,
        description="Field identifier",
        examples=["mcc"],
    )
    version: int = Field(
        ...,
        description="Version number",
        examples=[1],
    )
    field_id: int = Field(
        ...,
        description="Integer ID matching engine FieldRegistry",
        examples=[7],
    )
    display_name: str = Field(
        ...,
        description="Human-readable name",
    )
    description: str | None = Field(
        default=None,
        description="Field description",
    )
    data_type: str = Field(
        ...,
        description="Data type",
    )
    allowed_operators: list[str] = Field(
        ...,
        description="Allowed operators",
    )
    multi_value_allowed: bool = Field(
        ...,
        description="Whether multi-value is allowed",
    )
    is_sensitive: bool = Field(
        ...,
        description="Whether field contains sensitive data",
    )
    status: str = Field(
        ...,
        description="Governance status (DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, SUPERSEDED)",
    )
    created_by: str = Field(
        ...,
        description="User who created this version",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when version was created",
    )
    approved_by: str | None = Field(
        default=None,
        description="User who approved this version",
    )
    approved_at: datetime | None = Field(
        default=None,
        description="Timestamp when version was approved",
    )

    model_config = {
        "from_attributes": True,
    }


# ============================================================================
# FieldRegistryManifest Schemas
# ============================================================================


class FieldRegistryManifestResponse(BaseModel):
    """Schema for FieldRegistryManifest responses."""

    manifest_id: str = Field(
        ...,
        description="Unique identifier for the manifest",
    )
    registry_version: int = Field(
        ...,
        description="Registry version number",
    )
    artifact_uri: str = Field(
        ...,
        description="S3 URI of the published artifact",
    )
    checksum: str = Field(
        ...,
        description="SHA-256 checksum (sha256:<hex>)",
    )
    field_count: int = Field(
        ...,
        description="Number of fields in the registry",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when manifest was created",
    )
    created_by: str = Field(
        ...,
        description="User who triggered the publish",
    )

    model_config = {
        "from_attributes": True,
    }


# ============================================================================
# RuleFieldMetadata Schemas
# ============================================================================


class RuleFieldMetadataBase(BaseModel):
    """Base schema for RuleFieldMetadata operations."""

    meta_value: dict = Field(
        ...,
        description="JSONB metadata value (flexible key-value structure)",
        examples=[
            {
                "aggregation": "COUNT",
                "metric": "txn",
                "window": {"value": 10, "unit": "MINUTES"},
                "group_by": ["CARD"],
            }
        ],
    )

    @field_validator("meta_value")
    @classmethod
    def validate_meta_value_not_empty(cls, v: dict) -> dict:
        """Ensure meta_value is not an empty dict."""
        if not v:
            raise ValueError("meta_value cannot be empty")
        return v


class RuleFieldMetadataCreate(RuleFieldMetadataBase):
    """Schema for creating/upserting RuleFieldMetadata."""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "meta_value": {
                        "aggregation": "COUNT",
                        "metric": "txn",
                        "window": {"value": 10, "unit": "MINUTES"},
                        "group_by": ["CARD"],
                    }
                }
            ]
        }
    }


class RuleFieldMetadataResponse(RuleFieldMetadataBase):
    """Schema for RuleFieldMetadata responses."""

    field_key: str = Field(
        ...,
        description="The field this metadata belongs to",
        examples=["velocity_txn_count_10m_by_card"],
    )
    meta_key: str = Field(
        ...,
        description="Metadata key identifier",
        examples=["velocity"],
    )
    description: str | None = Field(
        default=None,
        description="Description of the metadata",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the metadata was created",
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "field_key": "velocity_txn_count_10m_by_card",
                    "meta_key": "velocity",
                    "meta_value": {
                        "aggregation": "COUNT",
                        "metric": "txn",
                        "window": {"value": 10, "unit": "MINUTES"},
                        "group_by": ["CARD"],
                    },
                    "created_at": "2026-01-01T12:00:00Z",
                }
            ]
        },
    }
