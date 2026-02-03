from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.validators import validate_condition_tree_depth, validate_condition_tree_node_count
from app.domain.enums import RuleAction, RuleType


def _validate_condition_tree(v: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate condition tree structure, depth, and node count."""
    if v is None:
        return v

    if not isinstance(v, dict):
        raise ValueError("condition_tree must be a dictionary")

    if not v:
        raise ValueError("condition_tree cannot be empty")

    # Validate tree depth (max 10 levels)
    try:
        validate_condition_tree_depth(v, max_depth=10)
    except ValueError as e:
        raise ValueError(str(e)) from e

    # Validate node count (max 1000 nodes to prevent DoS)
    try:
        validate_condition_tree_node_count(v, max_nodes=1000)
    except ValueError as e:
        raise ValueError(str(e)) from e

    # Validate array sizes (max 100 elements)
    def check_arrays(obj: Any, path: str = "") -> None:
        """Recursively check array sizes."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, list) and len(value) > 100:
                    raise ValueError(f"Array at '{path}.{key}' exceeds maximum size of 100")
                check_arrays(value, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                check_arrays(item, f"{path}[{i}]")

    try:
        check_arrays(v, "condition_tree")
    except ValueError as e:
        raise ValueError(str(e)) from e

    return v


class RuleCreate(BaseModel):
    rule_name: str
    description: str | None = None
    rule_type: RuleType
    condition_tree: dict[str, Any] | None = None
    priority: int = 100
    action: RuleAction | None = Field(
        default=None,
        description="Action when rule matches. Smart default based on rule_type when not provided.",
    )

    @model_validator(mode="before")
    @classmethod
    def set_smart_default_action(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Set smart default action based on rule_type when not provided."""
        # Make a copy to avoid modifying input
        result = data.copy()
        # Only set action if not provided
        if "action" not in result or result["action"] is None:
            rule_type = result.get("rule_type")
            # Handle both enum and string values
            if isinstance(rule_type, str):
                rule_type_str = rule_type
            elif isinstance(rule_type, RuleType):
                rule_type_str = rule_type.value
            else:
                rule_type_str = "ALLOWLIST"  # Default fallback

            # Set smart default based on rule_type
            if rule_type_str == "ALLOWLIST":
                result["action"] = RuleAction.APPROVE
            elif rule_type_str == "BLOCKLIST":
                result["action"] = RuleAction.DECLINE
            elif rule_type_str == "AUTH":
                result["action"] = RuleAction.DECLINE  # Default to safer option
            elif rule_type_str == "MONITORING":
                result["action"] = RuleAction.REVIEW
            else:
                result["action"] = RuleAction.REVIEW
        return result

    @field_validator("condition_tree")
    @classmethod
    def validate_condition_tree(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate condition tree structure and depth."""
        return _validate_condition_tree(v)

    @model_validator(mode="after")
    def validate_action_for_rule_type(self) -> RuleCreate:
        """
        Validate action matches rule type requirements.
        - ALLOWLIST: must be APPROVE (allow-list)
        - BLOCKLIST: must be DECLINE (block-list)
        - AUTH: must be APPROVE or DECLINE (real-time decisions, no REVIEW)
        - MONITORING: must be REVIEW (post-analytics only)
        """
        if self.rule_type == RuleType.ALLOWLIST and self.action != RuleAction.APPROVE:
            raise ValueError(
                f"ALLOWLIST rules must have action=APPROVE. Got: {self.action.value}. "
                "ALLOWLIST is an allow-list and always approves matching transactions."
            )
        if self.rule_type == RuleType.BLOCKLIST and self.action != RuleAction.DECLINE:
            raise ValueError(
                f"BLOCKLIST rules must have action=DECLINE. Got: {self.action.value}. "
                "BLOCKLIST is a block-list and always declines matching transactions."
            )
        if self.rule_type == RuleType.AUTH and self.action == RuleAction.REVIEW:
            raise ValueError(
                "AUTH rules cannot have action=REVIEW. "
                "AUTH is for real-time decisions and must be either APPROVE or DECLINE."
            )
        if self.rule_type == RuleType.MONITORING and self.action != RuleAction.REVIEW:
            raise ValueError(
                f"MONITORING rules must have action=REVIEW. Got: {self.action.value}. "
                "MONITORING is for post-analytics/alerting, not real-time decisions."
            )
        return self


class RuleResponse(BaseModel):
    rule_id: str
    rule_name: str
    description: str | None = None
    rule_type: str
    current_version: int
    status: str
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuleVersionCreate(BaseModel):
    condition_tree: dict[str, Any]
    priority: int = 100
    action: RuleAction | None = Field(
        default=None,
        description="Action when rule matches. If not provided, determined by rule_type.",
    )
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description='Optional scope dimensions (e.g., {"network": ["VISA"], "mcc": ["7995"]})',
    )
    expected_rule_version: int | None = Field(
        default=None,
        description=(
            "Expected version of the parent rule for optimistic locking. "
            "If provided, the operation will fail if the rule's version doesn't match."
        ),
    )

    @field_validator("condition_tree")
    @classmethod
    def validate_condition_tree(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate condition tree structure and depth."""
        result = _validate_condition_tree(v)
        if result is None:
            raise ValueError("condition_tree is required for RuleVersion")
        return result


class RuleVersionResponse(BaseModel):
    rule_version_id: str
    rule_id: str
    version: int
    condition_tree: dict[str, Any]
    priority: int
    action: str
    scope: dict[str, Any]
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class RuleVersionSubmitRequest(BaseModel):
    """Request to submit a rule version for approval."""

    idempotency_key: str | None = Field(
        default=None,
        description=(
            "Optional idempotency key to prevent duplicate submissions. "
            "If provided, the same key can be used to safely retry the submit "
            "operation without creating duplicate approvals."
        ),
        examples=["req_abc123xyz"],
    )
    remarks: str | None = Field(
        default=None,
        description="Optional remarks for the approval request",
    )


class RuleVersionApproveRequest(BaseModel):
    """Request to approve a rule version."""

    idempotency_key: str | None = Field(
        default=None,
        description=(
            "Optional idempotency key to prevent duplicate approvals. "
            "If provided, the same key can be used to safely retry the approve operation."
        ),
        examples=["req_xyz789abc"],
    )
    remarks: str | None = Field(
        default=None,
        description="Optional remarks for the approval",
    )


class RuleVersionRejectRequest(BaseModel):
    """Request to reject a rule version."""

    remarks: str | None = Field(
        default=None,
        description="Optional remarks explaining the rejection",
    )


class RuleVersionDetailResponse(BaseModel):
    """Detailed rule version response for analyst deep links."""

    rule_id: str
    rule_version_id: str
    version: int
    rule_name: str = Field(description="Rule name from parent Rule entity")
    rule_type: str = Field(description="Rule type from parent Rule entity")
    priority: int
    action: str
    scope: dict[str, Any]
    condition_tree: dict[str, Any]
    status: str
    created_at: datetime
    created_by: str
    approved_at: datetime | None = None
    approved_by: str | None = None


class RuleSummaryResponse(BaseModel):
    """Rule summary for analyst UI (lightweight response)."""

    rule_id: str
    rule_name: str
    rule_type: str
    status: str
    latest_version: int | None = None
    latest_version_id: str | None = None
    priority: int | None = None
    action: str | None = None


class RuleSimulateRequest(BaseModel):
    """Request to simulate a rule against historical transactions."""

    rule_type: RuleType = Field(description="Rule type being simulated (AUTH, MONITORING, etc.)")
    condition_tree: dict[str, Any] = Field(description="Condition tree AST to test")
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description='Optional scope dimensions (e.g., {"network": ["VISA"], "mcc": ["7995"]})',
    )
    query: dict[str, Any] = Field(
        description='Query parameters for simulation (e.g., {"from_date": "...", "to_date": "...", "risk_level": "HIGH"})',
    )

    @field_validator("condition_tree")
    @classmethod
    def validate_condition_tree(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate condition tree structure and depth."""
        result = _validate_condition_tree(v)
        if result is None:
            raise ValueError("condition_tree is required for simulation")
        return result


class RuleSimulateResponse(BaseModel):
    """Response from rule simulation."""

    match_count: int = Field(description="Number of transactions matching the rule condition")
    sample_transactions: list[str] = Field(
        description="Sample transaction IDs that matched the rule",
        default_factory=list,
    )
    simulation_id: str | None = Field(
        default=None,
        description="Optional simulation ID for tracking/resubmission",
    )
