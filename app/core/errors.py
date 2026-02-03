"""
Domain-specific exceptions for the Fraud Governance API.

These exceptions represent business logic violations and are mapped
to appropriate HTTP status codes in the API layer.
"""

from typing import Any


class FraudGovError(Exception):
    """Base exception for all fraud governance domain errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(FraudGovError):
    """
    Raised when input data fails validation.

    Examples:
    - Invalid condition tree structure
    - Required field missing
    - Data type mismatch
    - Business rule validation failure

    HTTP Status: 400 Bad Request
    """

    pass


class NotFoundError(FraudGovError):
    """
    Raised when a requested resource does not exist.

    Examples:
    - Rule ID not found
    - RuleSet not found
    - Field key not found

    HTTP Status: 404 Not Found
    """

    pass


class UnauthorizedError(FraudGovError):
    """
    Raised when user lacks permission for an operation.

    Examples:
    - Missing JWT token
    - Invalid JWT token
    - Insufficient permissions/roles
    - User not authenticated

    HTTP Status: 401 Unauthorized
    """

    pass


class ForbiddenError(FraudGovError):
    """
    Raised when user is authenticated but not allowed to perform action.

    Examples:
    - Attempting to approve own submission
    - Accessing resource outside user's scope

    HTTP Status: 403 Forbidden
    """

    pass


class MakerCheckerViolation(FraudGovError):
    """
    Raised when maker-checker workflow rules are violated.

    Examples:
    - Maker attempting to approve own submission
    - Checker same as maker (enforced by DB constraint)
    - Attempting to approve already-approved entity

    HTTP Status: 409 Conflict
    """

    pass


class ImmutableEntityError(FraudGovError):
    """
    Raised when attempting to modify an immutable entity.

    Examples:
    - Editing an APPROVED rule version
    - Modifying condition_tree after approval
    - Changing status from APPROVED to DRAFT

    HTTP Status: 409 Conflict
    """

    pass


class ConflictError(FraudGovError):
    """
    Raised when operation conflicts with current state.

    Examples:
    - Duplicate rule name
    - Version conflict
    - Status transition not allowed
    - Unique constraint violation

    HTTP Status: 409 Conflict
    """

    pass


class DependencyError(FraudGovError):
    """
    Raised when operation fails due to dependency constraints.

    Examples:
    - Cannot delete field used in active rules
    - Cannot delete rule version referenced by ruleset
    - Circular dependencies detected

    HTTP Status: 409 Conflict
    """

    pass


class CompilationError(FraudGovError):
    """
    Raised when AST compilation fails.

    Examples:
    - Invalid condition tree structure
    - Reference to non-existent field
    - Type mismatch in expression
    - Unsupported operator for data type

    HTTP Status: 422 Unprocessable Entity
    """

    pass


# HTTP Status Code Mapping
ERROR_STATUS_MAP = {
    ValidationError: 400,
    NotFoundError: 404,
    UnauthorizedError: 401,
    ForbiddenError: 403,
    MakerCheckerViolation: 409,
    ImmutableEntityError: 409,
    ConflictError: 409,
    DependencyError: 409,
    CompilationError: 422,
}


def get_status_code(error: Exception) -> int:
    """
    Get the HTTP status code for a given exception.

    Args:
        error: The exception instance

    Returns:
        HTTP status code (defaults to 500 for unknown errors)
    """
    return ERROR_STATUS_MAP.get(type(error), 500)
