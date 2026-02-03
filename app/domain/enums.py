"""
Domain enums matching the PostgreSQL database enums.

These enums provide type-safe representations of database enum types
and are used throughout the application for validation and type checking.
"""

from enum import Enum


class RuleType(str, Enum):
    """Type of fraud rule - matches fraud_gov.rule_type enum."""

    ALLOWLIST = "ALLOWLIST"
    BLOCKLIST = "BLOCKLIST"
    AUTH = "AUTH"
    MONITORING = "MONITORING"


class EntityStatus(str, Enum):
    """
    Lifecycle status for rules, rule versions, and rulesets.
    Matches fraud_gov.entity_status enum.

    Note: ACTIVE is only used for RuleSets (the currently deployed version).
    """

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    ACTIVE = "ACTIVE"  # Only for RuleSets


class ApprovalStatus(str, Enum):
    """Status of approval workflow - matches fraud_gov.approval_status enum."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalEntityType(str, Enum):
    """Type of entity being approved - matches fraud_gov.approval_entity_type enum."""

    RULE_VERSION = "RULE_VERSION"
    RULESET_VERSION = "RULESET_VERSION"
    FIELD_VERSION = "FIELD_VERSION"


class AuditEntityType(str, Enum):
    """Type of entity being audited - matches fraud_gov.audit_entity_type enum."""

    RULE_FIELD = "RULE_FIELD"
    RULE_FIELD_METADATA = "RULE_FIELD_METADATA"
    RULE = "RULE"
    RULE_VERSION = "RULE_VERSION"
    RULESET = "RULESET"
    RULESET_VERSION = "RULESET_VERSION"
    APPROVAL = "APPROVAL"
    FIELD_VERSION = "FIELD_VERSION"
    FIELD_REGISTRY_MANIFEST = "FIELD_REGISTRY_MANIFEST"


class DataType(str, Enum):
    """
    Data types for rule fields.
    Constraint: rule_fields.data_type must be one of these values.
    """

    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    ENUM = "ENUM"


class Operator(str, Enum):
    """
    Supported operators for rule conditions.
    Used in rule_fields.allowed_operators array.
    """

    EQ = "EQ"  # Equal
    NE = "NE"  # Not Equal
    IN = "IN"  # In list
    NOT_IN = "NOT_IN"  # Not in list
    GT = "GT"  # Greater than
    GTE = "GTE"  # Greater than or equal
    LT = "LT"  # Less than
    LTE = "LTE"  # Less than or equal
    BETWEEN = "BETWEEN"  # Between two values
    CONTAINS = "CONTAINS"  # String contains
    STARTS_WITH = "STARTS_WITH"  # String starts with
    ENDS_WITH = "ENDS_WITH"  # String ends with
    REGEX = "REGEX"  # Regular expression match


class ApprovalAction(str, Enum):
    """
    Actions in approval workflow.
    Constraint: approvals.action must be one of these values.
    """

    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RuleAction(str, Enum):
    """
    Action to take when a rule matches.
    Must match runtime Decision.java values.
    """

    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    REVIEW = "REVIEW"
