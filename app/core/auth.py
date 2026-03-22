"""Typed authentication model shared by security helpers and dependencies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthenticatedUser(BaseModel):
    """Authenticated user information extracted from an Auth0 token."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    email: str | None = None
    name: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)

    @property
    def sub(self) -> str:
        """Auth0 subject alias used by existing helper code."""
        return self.user_id

    @property
    def is_platform_admin(self) -> bool:
        """Return True when the user has the platform admin role."""
        return "PLATFORM_ADMIN" in self.roles

    @property
    def is_fraud_analyst(self) -> bool:
        """Return True when the user has the fraud analyst role."""
        return "FRAUD_ANALYST" in self.roles or self.is_platform_admin

    @property
    def is_fraud_supervisor(self) -> bool:
        """Return True when the user has the fraud supervisor role."""
        return "FRAUD_SUPERVISOR" in self.roles or self.is_platform_admin

    def has_permission(self, permission: str) -> bool:
        """Return True when the user has the requested permission."""
        return permission in self.permissions or self.is_platform_admin

    def has_role(self, role: str) -> bool:
        """Return True when the user has the requested role."""
        return role in self.roles

    def get(self, key: str, default=None):
        """Compatibility helper for legacy dict-style access."""
        if key in {"sub", "user_id"}:
            return self.user_id
        return getattr(self, key, default)
