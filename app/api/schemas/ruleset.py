"""Pydantic schemas for RuleSet and RuleSetVersion API requests/responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# =============================================================================
# Ruleset Identity Schemas
# =============================================================================


class RuleSetCreate(BaseModel):
    """Create a new ruleset identity."""

    environment: str = Field(min_length=1, description="Environment name (local, dev, test, prod)")
    region: str = Field(
        min_length=1, description="Infrastructure boundary (APAC, EMEA, INDIA, AMERICAS)"
    )
    country: str = Field(min_length=1, description="Country code (IN, SG, HK, UK, etc.)")
    rule_type: str = Field(
        min_length=1, description="Rule type (ALLOWLIST, BLOCKLIST, AUTH, MONITORING)"
    )
    name: str | None = Field(None, description="Human-readable name for the ruleset")
    description: str | None = Field(None, description="Description of the ruleset purpose")

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        allowed = {"ALLOWLIST", "BLOCKLIST", "AUTH", "MONITORING"}
        if v.upper() not in allowed:
            raise ValueError(f"rule_type must be one of {allowed}")
        return v.upper()


class RuleSetUpdate(BaseModel):
    """Update ruleset identity metadata."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2000)


class RuleSetResponse(BaseModel):
    """Ruleset identity response."""

    ruleset_id: str
    environment: str
    region: str
    country: str
    rule_type: str
    name: str | None = None
    description: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuleSetWithVersionResponse(RuleSetResponse):
    """Ruleset identity with optional latest/active version info."""

    latest_version: RuleSetVersionResponse | None = None
    active_version: RuleSetVersionResponse | None = None


class RuleSetListParams(BaseModel):
    """Query parameters for listing rulesets."""

    rule_type: str | None = None
    environment: str | None = None
    region: str | None = None
    country: str | None = None
    include_versions: bool = False
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = None
    direction: str = Field(default="next", pattern="^(next|prev)$")


# =============================================================================
# Ruleset Version Schemas
# =============================================================================


class RuleSetVersionCreate(BaseModel):
    """Create a new version of a ruleset."""

    rule_version_ids: list[UUID] = Field(
        default_factory=list,
        description="List of approved rule version IDs to include in this ruleset version",
    )

    @field_validator("rule_version_ids")
    @classmethod
    def validate_max_rules(cls, v: list[UUID]) -> list[UUID]:
        if len(v) > 100:
            raise ValueError(f"Cannot include more than 100 rules (got {len(v)})")
        if len(v) == 0:
            raise ValueError("At least one rule version must be included")
        return v


class RuleSetVersionResponse(BaseModel):
    """Ruleset version response."""

    ruleset_version_id: str
    ruleset_id: str
    version: int
    status: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    activated_at: datetime | None = None
    # Optionally include related rule versions
    rule_versions: list[RuleVersionInRuleset] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RuleVersionInRuleset(BaseModel):
    """Rule version as included in a ruleset."""

    rule_version_id: str
    rule_id: str
    version: int
    rule_name: str  # From parent rule
    rule_type: str  # From parent rule
    priority: int
    scope: dict
    status: str

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Ruleset Version Actions
# =============================================================================


class RuleSetVersionSubmitRequest(BaseModel):
    """Submit a ruleset version for approval."""

    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate submissions",
    )


class RuleSetVersionApproveRequest(BaseModel):
    """Approve a ruleset version (triggers publishing)."""

    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate approvals",
    )


class RuleSetVersionRejectRequest(BaseModel):
    """Reject a ruleset version."""

    remarks: str | None = Field(
        default=None,
        description="Optional remarks explaining the rejection",
    )


class RuleSetVersionActivateRequest(BaseModel):
    """Activate a ruleset version (makes it live for runtime)."""

    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate activations",
    )


# =============================================================================
# Compile/Compilation Result Schemas
# =============================================================================


class CompiledRule(BaseModel):
    """A single rule in the compiled AST."""

    ruleId: str
    ruleVersionId: str
    priority: int
    scope: dict
    when: dict
    action: str


class CompiledEvaluation(BaseModel):
    """Evaluation configuration for the ruleset."""

    mode: str  # FIRST_MATCH or ALL_MATCHING


class CompiledAstStructure(BaseModel):
    """The complete compiled AST structure for a ruleset."""

    rulesetId: str
    version: int
    ruleType: str
    evaluation: CompiledEvaluation
    velocityFailurePolicy: str
    rules: list[CompiledRule]


class CompiledAstResponse(BaseModel):
    """Response containing the compiled AST (in-memory only, not stored in DB)."""

    ruleset_version_id: str
    compiled_ast: CompiledAstStructure
    checksum: str  # SHA-256 of the serialized AST
    can_publish: bool  # Whether all rules are approved
    warnings: list[str] = Field(default_factory=list)


# =============================================================================
# Manifest Schemas
# =============================================================================


class RuleSetManifestResponse(BaseModel):
    """Published ruleset manifest response."""

    ruleset_manifest_id: str
    environment: str
    region: str
    country: str
    rule_type: str
    ruleset_version: int
    ruleset_version_id: str
    artifact_uri: str
    checksum: str
    created_at: datetime
    created_by: str

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Legacy Schemas (for backward compatibility during migration)
# =============================================================================


class RuleSetAttachRuleVersions(BaseModel):
    """Legacy schema for attaching rule versions to a ruleset."""

    rule_version_ids: list[UUID] = Field(
        default_factory=list,
        description="List of rule version IDs to attach to this ruleset",
    )
    expected_ruleset_version: int | None = Field(
        default=None,
        description="Expected version of the ruleset for optimistic locking",
    )

    @field_validator("rule_version_ids")
    @classmethod
    def validate_max_rules(cls, v: list[UUID]) -> list[UUID]:
        """Ensure we don't exceed maximum rules per ruleset."""
        if len(v) > 100:
            raise ValueError(f"Cannot attach more than 100 rules to a ruleset (got {len(v)})")
        return v


class RuleSetSubmitRequest(BaseModel):
    """Request to submit a ruleset for approval (legacy)."""

    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate submissions",
    )


class RuleSetApproveRequest(BaseModel):
    """Request to approve a ruleset (legacy)."""

    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate approvals",
    )


class RuleSetRejectRequest(BaseModel):
    """Request to reject a ruleset (legacy)."""

    remarks: str | None = Field(
        default=None,
        description="Optional remarks explaining the rejection",
    )
