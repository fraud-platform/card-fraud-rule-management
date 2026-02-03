"""Tests for common repository functions.

These tests verify the async versions of common repo functions.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid7

import pytest

from app.domain.enums import ApprovalStatus


class TestCommonRepo:
    """Test async versions of common repository functions."""

    @pytest.mark.anyio
    async def test_get_pending_approval_found(self):
        """Test that get_pending_approval finds pending approvals."""
        from app.repos.common import get_pending_approval

        # Create mock approval
        mock_approval = MagicMock()
        mock_approval.approval_id = str(uuid7())
        mock_approval.status = ApprovalStatus.PENDING

        # Create mock result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_approval)

        # Create mock session
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        entity_id = str(uuid7())
        result = await get_pending_approval(mock_db, entity_id=entity_id)

        assert result == mock_approval
        mock_db.execute.assert_called_once()

    @pytest.mark.anyio
    async def test_get_pending_approval_not_found(self):
        """Test that get_pending_approval returns None when not found."""
        from app.repos.common import get_pending_approval

        # Create mock result with no approval
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

        # Create mock session
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        entity_id = str(uuid7())
        result = await get_pending_approval(mock_db, entity_id=entity_id)

        assert result is None

    @pytest.mark.anyio
    async def test_increment_rule_version_increments(self):
        """Test that increment_rule_version increments the version."""
        from app.repos.common import increment_rule_version

        rule_id = str(uuid7())
        new_version = 42

        # Create mock result
        mock_result = MagicMock()
        mock_result.scalar_one = MagicMock(return_value=new_version)

        # Create mock session
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await increment_rule_version(mock_db, rule_id=rule_id)

        assert result == new_version
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()


class TestMakerChecker:
    """Test maker-checker validation."""

    @pytest.mark.anyio
    async def test_check_maker_not_checker_raises_on_same_user(self):
        """Test that check_maker_not_checker raises when maker == checker."""
        from app.core.errors import MakerCheckerViolation
        from app.repos.common import check_maker_not_checker

        with pytest.raises(MakerCheckerViolation):
            check_maker_not_checker("same_user", "same_user")

    @pytest.mark.anyio
    async def test_check_maker_not_checker_passes_on_different_users(self):
        """Test that check_maker_not_checker passes when maker != checker."""
        from app.repos.common import check_maker_not_checker

        # Should not raise
        check_maker_not_checker("maker_user", "checker_user")


class TestApprovalUpdate:
    """Test approval update functions."""

    @pytest.mark.anyio
    async def test_update_approval_approved_sets_fields(self):
        """Test that update_approval_approved sets all required fields."""
        from app.db.models import Approval
        from app.domain.enums import ApprovalStatus
        from app.repos.common import update_approval_approved

        approval = MagicMock(spec=Approval)
        checker = "checker@example.com"
        remarks = "Approved after review"

        await update_approval_approved(None, approval, checker, remarks)

        assert approval.checker == checker
        assert approval.status == ApprovalStatus.APPROVED
        assert approval.decided_at is not None
        assert approval.remarks == remarks

    @pytest.mark.anyio
    async def test_update_approval_approved_without_remarks(self):
        """Test that update_approval_approved works without remarks."""
        from app.db.models import Approval
        from app.domain.enums import ApprovalStatus
        from app.repos.common import update_approval_approved

        approval = MagicMock(spec=Approval)
        checker = "checker@example.com"

        await update_approval_approved(None, approval, checker)

        assert approval.checker == checker
        assert approval.status == ApprovalStatus.APPROVED
        assert approval.decided_at is not None


class TestApprovalAuditLog:
    """Test approval audit log creation."""

    @pytest.mark.anyio
    async def test_create_approval_audit_log_creates_log(self):
        """Test that create_approval_audit_log creates an audit log entry."""
        from app.repos.common import create_approval_audit_log

        entity_type = "RULE_VERSION"
        entity_id = str(uuid7())
        checker = "checker@example.com"
        old_value = {"status": "PENDING"}
        new_value = {"status": "APPROVED"}

        with patch("app.repos.common.create_audit_log_async") as mock_create_log:
            await create_approval_audit_log(
                None,
                entity_type=entity_type,
                entity_id=entity_id,
                checker=checker,
                old_value=old_value,
                new_value=new_value,
            )

            mock_create_log.assert_called_once()

    @pytest.mark.anyio
    async def test_create_approval_audit_log_with_details(self):
        """Test that create_approval_audit_log includes extra details."""
        from app.repos.common import create_approval_audit_log

        include_details = {"manifest_id": "test-manifest-123"}

        with patch("app.repos.common.create_audit_log_async") as mock_create_log:
            await create_approval_audit_log(
                None,
                entity_type="RULESET_VERSION",
                entity_id=str(uuid7()),
                checker="checker@example.com",
                old_value={"status": "PENDING"},
                new_value={"status": "APPROVED"},
                include_details=include_details,
            )

            # Check that the new_value includes the extra details
            call_args = mock_create_log.call_args
            assert call_args is not None
            passed_new_value = call_args.kwargs.get("new_value", {})
            assert passed_new_value.get("manifest_id") == "test-manifest-123"
