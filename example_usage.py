"""
Example usage of Auth0 JWT authentication in FastAPI endpoints.

This file demonstrates how to use the authentication and authorization
dependencies in your API routes.
"""

from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession, RequireAdmin, RequireChecker, RequireMaker

# Create example router
router = APIRouter(prefix="/api/v1", tags=["examples"])


# ============================================================================
# Example 1: Endpoint requiring authentication (any authenticated user)
# ============================================================================


@router.get("/profile")
def get_user_profile(user: CurrentUser):
    """
    Get the current user's profile.

    Any authenticated user can access this endpoint.
    No specific role is required.

    Args:
        user: Current authenticated user (injected by CurrentUser dependency)

    Returns:
        User profile information
    """
    return {
        "user_id": user["sub"],
        "roles": user.get("https://fraud-governance-api/roles", []),
        "authenticated": True,
    }


# ============================================================================
# Example 2: Endpoint requiring MAKER role
# ============================================================================


@router.post("/rules")
def create_rule(rule_data: dict, user: RequireMaker, db: DbSession):
    """
    Create a new fraud rule (DRAFT status).

    Only users with the MAKER role can create rules.

    Args:
        rule_data: Rule definition
        user: Current user (must have MAKER role)
        db: Database session

    Returns:
        Created rule information
    """
    return {
        "message": "Rule created",
        "created_by": user["sub"],
        "rule_data": rule_data,
        "status": "DRAFT",
    }


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, rule_data: dict, user: RequireMaker, db: DbSession):
    """
    Update an existing DRAFT rule.

    Only users with the MAKER role can update rules.
    Users can only update rules in DRAFT status.

    Args:
        rule_id: ID of the rule to update
        rule_data: Updated rule definition
        user: Current user (must have MAKER role)
        db: Database session

    Returns:
        Updated rule information
    """
    return {
        "message": "Rule updated",
        "rule_id": rule_id,
        "updated_by": user["sub"],
        "rule_data": rule_data,
    }


# ============================================================================
# Example 3: Endpoint requiring CHECKER role
# ============================================================================


@router.post("/rules/{rule_id}/approve")
def approve_rule(rule_id: int, user: RequireChecker, db: DbSession):
    """
    Approve a rule (maker-checker workflow).

    Only users with the CHECKER role can approve rules.
    Business logic should verify that checker != maker.

    Args:
        rule_id: ID of the rule to approve
        user: Current user (must have CHECKER role)
        db: Database session

    Returns:
        Approval confirmation
    """
    return {
        "message": "Rule approved",
        "rule_id": rule_id,
        "approved_by": user["sub"],
        "status": "APPROVED",
    }


@router.post("/rules/{rule_id}/reject")
def reject_rule(rule_id: int, reason: str, user: RequireChecker, db: DbSession):
    """
    Reject a rule.

    Only users with the CHECKER role can reject rules.

    Args:
        rule_id: ID of the rule to reject
        reason: Reason for rejection
        user: Current user (must have CHECKER role)
        db: Database session

    Returns:
        Rejection confirmation
    """
    return {
        "message": "Rule rejected",
        "rule_id": rule_id,
        "rejected_by": user["sub"],
        "reason": reason,
        "status": "REJECTED",
    }


# ============================================================================
# Example 4: Endpoint requiring ADMIN role
# ============================================================================


@router.post("/fields")
def create_field(field_data: dict, user: RequireAdmin, db: DbSession):
    """
    Create a new field definition.

    Only users with the ADMIN role can manage field definitions.

    Args:
        field_data: Field definition
        user: Current user (must have ADMIN role)
        db: Database session

    Returns:
        Created field information
    """
    return {
        "message": "Field created",
        "created_by": user["sub"],
        "field_data": field_data,
    }


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, user: RequireAdmin, db: DbSession):
    """
    Delete a field definition.

    Only users with the ADMIN role can delete fields.
    Business logic should check that the field is not in use.

    Args:
        field_id: ID of the field to delete
        user: Current user (must have ADMIN role)
        db: Database session

    Returns:
        Deletion confirmation
    """
    return {
        "message": "Field deleted",
        "field_id": field_id,
        "deleted_by": user["sub"],
    }


# ============================================================================
# Example 5: Manual role checking for complex logic
# ============================================================================


@router.post("/rules/{rule_id}/publish")
def publish_rule(rule_id: int, user: CurrentUser, db: DbSession):
    """
    Publish an APPROVED rule to production.

    This endpoint allows either CHECKER or ADMIN roles.
    Demonstrates manual role checking for complex authorization logic.

    Args:
        rule_id: ID of the rule to publish
        user: Current user (must have CHECKER or ADMIN role)
        db: Database session

    Returns:
        Publication confirmation
    """
    from app.core.errors import ForbiddenError
    from app.core.security import get_user_roles

    # Get user roles
    roles = get_user_roles(user)

    # Check if user has either CHECKER or ADMIN role
    if "CHECKER" not in roles and "ADMIN" not in roles:
        raise ForbiddenError(
            "Insufficient permissions",
            details={
                "required_roles": ["CHECKER", "ADMIN"],
                "user_roles": roles,
            },
        )

    return {
        "message": "Rule published to production",
        "rule_id": rule_id,
        "published_by": user["sub"],
        "status": "PUBLISHED",
    }


# ============================================================================
# Example 6: Extracting additional user information
# ============================================================================


@router.get("/audit/my-actions")
def get_my_audit_trail(user: CurrentUser, db: DbSession):
    """
    Get audit trail for the current user.

    Shows how to extract user ID for filtering database queries.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        User's audit trail
    """
    from app.core.security import get_user_sub

    user_id = get_user_sub(user)

    # In a real implementation, you would query the database:
    # audit_records = db.query(AuditLog).filter(AuditLog.user_id == user_id).all()

    return {
        "user_id": user_id,
        "message": "This would return the user's audit trail from the database",
    }


# ============================================================================
# Usage Notes
# ============================================================================

"""
To use these endpoints in your FastAPI application:

1. Add this router to your main.py:

   from example_usage import router as example_router
   app.include_router(example_router)

2. Start the server:

   uv run uvicorn app.main:app --reload

3. Test with a valid Auth0 JWT token:

   curl -H "Authorization: Bearer <your_token>" \\
        http://localhost:8000/api/v1/profile

4. The token should contain:
   {
     "iss": "https://dev-xxxl8.us.auth0.com/",
     "sub": "google-oauth2|123456789",
     "aud": "https://fraud-governance-api",
     "exp": 1234567890,
     "https://fraud-governance-api/roles": ["MAKER", "CHECKER"]
   }

Error Responses:
- 401 Unauthorized: Invalid or missing token
- 403 Forbidden: Valid token but insufficient permissions
- 400 Bad Request: Validation error
- 404 Not Found: Resource not found
- 500 Internal Server Error: Unexpected error
"""
