"""DB-backed repository functions for RuleSet lifecycle and compilation.

Updated for v1 schema:
- RuleSet: Identity table (environment, region, country, rule_type)
- RuleSetVersion: Immutable snapshots with status
- RuleSetVersionRule: Join table linking versions to rule versions
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.keyset_pagination import CursorDirection
from app.compiler.compiler import compile_ruleset as compile_ruleset_ast
from app.core.audit import create_audit_log_async, snapshot_entity
from app.core.errors import (
    CompilationError,
    ConflictError,
    MakerCheckerViolation,
    NotFoundError,
    ValidationError,
)
from app.core.notifications import notify
from app.db.models import (
    Approval,
    Rule,
    RuleSet,
    RuleSetVersion,
    RuleSetVersionRule,
    RuleVersion,
)
from app.domain.enums import EntityStatus, RuleType
from app.repos.common import (
    check_maker_not_checker,
    create_approval_audit_log,
    get_pending_approval,
    update_approval_approved,
)
from app.repos.pagination import build_keyset_query, decode_cursor, get_keyset_page_info

logger = logging.getLogger(__name__)


async def _ruleset_version_member_ids(
    db: AsyncSession, ruleset_version_id: UUID | str
) -> list[str]:
    """Compact membership summary for audits - queries DB directly to avoid lazy loading."""
    stmt = select(RuleSetVersionRule.rule_version_id).where(
        RuleSetVersionRule.ruleset_version_id == str(ruleset_version_id)
    )
    result = await db.execute(stmt)
    return [str(m[0]) for m in result.all()]


async def _get_ruleset(db: AsyncSession, ruleset_id: UUID | str) -> RuleSet:
    """Get ruleset by ID, raising NotFoundError if not found."""
    stmt = select(RuleSet).where(RuleSet.ruleset_id == ruleset_id)
    result = await db.execute(stmt)
    ruleset = result.scalar_one_or_none()
    if not ruleset:
        raise NotFoundError("Ruleset not found", details={"ruleset_id": str(ruleset_id)})
    return ruleset


async def _auto_approve_rule_versions(
    db: AsyncSession, version: RuleSetVersion, checker: str, now: datetime
) -> None:
    """Approve all non-approved rule versions in the ruleset."""
    from sqlalchemy.orm import joinedload

    stmt = (
        select(RuleVersion)
        .options(joinedload(RuleVersion.rule))  # Eager load to avoid N+1
        .join(RuleSetVersionRule, RuleSetVersionRule.rule_version_id == RuleVersion.rule_version_id)
        .where(RuleSetVersionRule.ruleset_version_id == version.ruleset_version_id)
    )
    result = await db.execute(stmt)
    members = result.unique().scalars().all()

    for mv in members:
        if mv.status != EntityStatus.APPROVED:
            # Rule already loaded via joinedload
            rule = mv.rule

            old_value_rv = {
                **snapshot_entity(mv, include=["status", "approved_by", "approved_at"]),
                "rule_id": str(mv.rule_id),
                "rule_name": rule.rule_name if rule else None,
                "version": mv.version,
                "priority": mv.priority,
            }

            prev_stmt = select(RuleVersion).where(
                RuleVersion.rule_id == mv.rule_id, RuleVersion.status == EntityStatus.APPROVED
            )
            prev_result = await db.execute(prev_stmt)
            prev_versions = prev_result.scalars().all()
            for pv in prev_versions:
                pv.status = EntityStatus.SUPERSEDED

            mv.status = EntityStatus.APPROVED
            mv.approved_by = checker
            mv.approved_at = now

            await create_audit_log_async(
                db,
                entity_type="RULE_VERSION",
                entity_id=str(mv.rule_version_id),
                action="APPROVE",
                old_value=old_value_rv,
                new_value={
                    **snapshot_entity(mv, include=["status", "approved_by", "approved_at"]),
                    "rule_id": str(mv.rule_id),
                    "rule_name": rule.rule_name if rule else None,
                    "version": mv.version,
                    "priority": mv.priority,
                },
                performed_by=checker,
            )

    await db.flush()


async def _supersede_previous_ruleset_versions(db: AsyncSession, version: RuleSetVersion) -> None:
    """Mark previous APPROVED/ACTIVE versions as SUPERSEDED."""
    stmt = select(RuleSetVersion).where(
        RuleSetVersion.ruleset_id == version.ruleset_id,
        RuleSetVersion.ruleset_version_id != version.ruleset_version_id,
        RuleSetVersion.status.in_((EntityStatus.APPROVED, EntityStatus.ACTIVE)),
    )
    result = await db.execute(stmt)
    prev_versions = result.scalars().all()
    for pv in prev_versions:
        pv.status = EntityStatus.SUPERSEDED


async def _publish_ruleset_artifact(
    db: AsyncSession, version: RuleSetVersion, ruleset: RuleSet, checker: str
) -> str | None:
    """Compile and publish ruleset artifact. Returns manifest_id or None."""
    if ruleset.rule_type not in (RuleType.AUTH, RuleType.MONITORING):
        return None

    try:
        compiled_ast = await compile_ruleset_ast(
            str(ruleset.ruleset_id), db, ruleset_version_id=version.ruleset_version_id
        )

        from app.services.ruleset_publisher import publish_ruleset_version

        manifest = await publish_ruleset_version(
            db=db,
            ruleset_version=version,
            ruleset=ruleset,
            compiled_ast=compiled_ast,
            checker=checker,
        )
        manifest_id = str(manifest.ruleset_manifest_id)
        logger.info(
            f"Published ruleset version {version.ruleset_version_id} manifest {manifest_id}"
        )
        return manifest_id
    except ValidationError:
        logger.debug(
            f"Skipping artifact publication for ruleset version {version.ruleset_version_id}"
        )
        return None


# =============================================================================
# Ruleset Identity Operations
# =============================================================================


async def list_rulesets(
    db: AsyncSession,
    *,
    cursor: str | None = None,
    limit: int = 50,
    direction: CursorDirection = CursorDirection.NEXT,
    rule_type: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    country: str | None = None,
) -> tuple[list[RuleSet], bool, bool, str | None, str | None]:
    """List ruleset identities with keyset/cursor-based pagination.

    Args:
        db: Database session
        cursor: Base64-encoded cursor from previous page
        limit: Number of items per page
        direction: NEXT for forward pagination, PREV for backward
        rule_type: Optional filter by rule type
        environment: Optional filter by environment
        region: Optional filter by region
        country: Optional filter by country

    Returns:
        Tuple of (list of rulesets, has_next, has_prev, next_cursor, prev_cursor)
    """
    cursor_tuple = None
    is_first_page = cursor is None
    if cursor:
        cursor_tuple = decode_cursor(cursor)

    # Build query with keyset pagination
    stmt = build_keyset_query(
        RuleSet,
        cursor=cursor_tuple,
        direction=direction,
        limit=limit,
        order_column="created_at",
        id_column="ruleset_id",
    )

    # Add filters
    if rule_type:
        stmt = stmt.where(RuleSet.rule_type == rule_type)
    if environment:
        stmt = stmt.where(RuleSet.environment == environment)
    if region:
        stmt = stmt.where(RuleSet.region == region)
    if country:
        stmt = stmt.where(RuleSet.country == country)

    result = await db.execute(stmt)
    rulesets = result.scalars().all()
    rulesets_list = list(rulesets)

    trimmed_rulesets, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
        rulesets_list, limit, direction, is_first_page=is_first_page
    )

    return trimmed_rulesets, has_next, has_prev, next_cursor, prev_cursor


async def create_ruleset(
    db: AsyncSession,
    *,
    environment: str,
    region: str,
    country: str,
    rule_type: str,
    name: str | None,
    description: str | None,
    created_by: str,
) -> RuleSet:
    """Create a new ruleset identity.

    Args:
        db: Database session
        environment: Environment name (local, dev, test, prod)
        region: Infrastructure boundary (APAC, EMEA, INDIA, AMERICAS)
        country: Country code (IN, SG, HK, UK, etc.)
        rule_type: Rule type (ALLOWLIST, BLOCKLIST, AUTH, MONITORING)
        name: Human-readable name
        description: Ruleset description
        created_by: User creating the ruleset

    Returns:
        Created RuleSet

    Raises:
        ConflictError: If ruleset with same (environment, region, country, rule_type) exists
    """
    # Check for existing ruleset with same scope
    stmt = select(RuleSet).where(
        RuleSet.environment == environment,
        RuleSet.region == region,
        RuleSet.country == country,
        RuleSet.rule_type == rule_type,
    )
    existing_result = await db.execute(stmt)
    existing = existing_result.scalar_one_or_none()

    if existing:
        raise ConflictError(
            "Ruleset already exists for this scope",
            details={
                "environment": environment,
                "region": region,
                "country": country,
                "rule_type": rule_type,
                "existing_ruleset_id": str(existing.ruleset_id),
            },
        )

    ruleset = RuleSet(
        environment=environment,
        region=region,
        country=country,
        rule_type=rule_type,
        name=name,
        description=description,
        created_by=created_by,
    )
    db.add(ruleset)
    await db.flush()

    logger.info(
        "Created ruleset %s (env=%s,region=%s,country=%s,type=%s)",
        ruleset.ruleset_id,
        environment,
        region,
        country,
        rule_type,
    )
    return ruleset


async def get_ruleset(db: AsyncSession, ruleset_id: UUID | str) -> RuleSet:
    """Get a ruleset identity by ID.

    Args:
        db: Database session
        ruleset_id: RuleSet UUID

    Returns:
        RuleSet

    Raises:
        NotFoundError: If ruleset not found
    """
    stmt = select(RuleSet).where(RuleSet.ruleset_id == ruleset_id)
    result = await db.execute(stmt)
    ruleset = result.scalar_one_or_none()
    if not ruleset:
        raise NotFoundError("Ruleset not found", details={"ruleset_id": str(ruleset_id)})
    return ruleset


async def update_ruleset(
    db: AsyncSession,
    *,
    ruleset_id: UUID | str,
    name: str | None,
    description: str | None,
    modified_by: str,
) -> RuleSet:
    """Update ruleset identity metadata.

    Args:
        db: Database session
        ruleset_id: RuleSet UUID
        name: New name (optional)
        description: New description (optional)
        modified_by: User making the change

    Returns:
        Updated RuleSet

    Raises:
        NotFoundError: If ruleset not found
    """
    ruleset = await get_ruleset(db, ruleset_id)

    old_value = snapshot_entity(ruleset, include=["name", "description"])

    if name is not None:
        ruleset.name = name
    if description is not None:
        ruleset.description = description

    await db.flush()

    new_value = snapshot_entity(ruleset, include=["name", "description"])

    await create_audit_log_async(
        db,
        entity_type="RULESET",
        entity_id=str(ruleset.ruleset_id),
        action="UPDATE",
        old_value=old_value,
        new_value=new_value,
        performed_by=modified_by,
    )

    logger.info("Updated ruleset %s metadata", ruleset.ruleset_id)
    return ruleset


async def get_ruleset_by_scope(
    db: AsyncSession, *, environment: str, region: str, country: str, rule_type: str
) -> RuleSet | None:
    """Get a ruleset by its scope.

    Args:
        db: Database session
        environment: Environment name
        region: Region
        country: Country code
        rule_type: Rule type

    Returns:
        RuleSet or None if not found
    """
    stmt = select(RuleSet).where(
        RuleSet.environment == environment,
        RuleSet.region == region,
        RuleSet.country == country,
        RuleSet.rule_type == rule_type,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# =============================================================================
# Ruleset Version Operations
# =============================================================================


async def list_ruleset_versions(
    db: AsyncSession,
    *,
    ruleset_id: UUID | str,
    cursor: str | None = None,
    limit: int = 50,
    direction: CursorDirection = CursorDirection.NEXT,
    status: str | None = None,
) -> tuple[list[RuleSetVersion], bool, bool, str | None, str | None]:
    """List all versions of a ruleset.

    Args:
        db: Database session
        ruleset_id: RuleSet UUID
        cursor: Base64-encoded cursor
        limit: Number of items per page
        direction: NEXT for forward, PREV for backward
        status: Optional filter by status

    Returns:
        Tuple of (list of versions, has_next, has_prev, next_cursor, prev_cursor)
    """
    cursor_tuple = None
    is_first_page = cursor is None
    if cursor:
        cursor_tuple = decode_cursor(cursor)

    # Build query with keyset pagination
    stmt = build_keyset_query(
        RuleSetVersion,
        cursor=cursor_tuple,
        direction=direction,
        limit=limit,
        order_column="created_at",
        id_column="ruleset_version_id",
    ).where(RuleSetVersion.ruleset_id == ruleset_id)

    if status:
        stmt = stmt.where(RuleSetVersion.status == status)

    result = await db.execute(stmt)
    versions = result.scalars().all()
    versions_list = list(versions)

    trimmed_versions, has_next, has_prev, next_cursor, prev_cursor = get_keyset_page_info(
        versions_list, limit, direction, is_first_page=is_first_page
    )

    return trimmed_versions, has_next, has_prev, next_cursor, prev_cursor


async def get_ruleset_version(
    db: AsyncSession, ruleset_version_id: UUID | str, include_rules: bool = False
) -> RuleSetVersion:
    """Get a ruleset version by ID.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        include_rules: Whether to include rule memberships

    Returns:
        RuleSetVersion

    Raises:
        NotFoundError: If version not found
    """
    stmt = select(RuleSetVersion).where(RuleSetVersion.ruleset_version_id == ruleset_version_id)
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        raise NotFoundError(
            "Ruleset version not found", details={"ruleset_version_id": str(ruleset_version_id)}
        )
    return version


async def get_active_ruleset_version(
    db: AsyncSession, *, environment: str, region: str, country: str, rule_type: str
) -> RuleSetVersion | None:
    """Get the active ruleset version for a given scope.

    Args:
        db: Database session
        environment: Environment name
        region: Region
        country: Country code
        rule_type: Rule type

    Returns:
        Active RuleSetVersion or None
    """
    # First get the ruleset
    ruleset = await get_ruleset_by_scope(
        db, environment=environment, region=region, country=country, rule_type=rule_type
    )
    if not ruleset:
        return None

    # Get the active version
    stmt = (
        select(RuleSetVersion)
        .where(
            RuleSetVersion.ruleset_id == ruleset.ruleset_id,
            RuleSetVersion.status == EntityStatus.ACTIVE,
        )
        .order_by(RuleSetVersion.activated_at.desc())
    )

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_ruleset_version(
    db: AsyncSession, *, ruleset_id: UUID | str, created_by: str
) -> RuleSetVersion:
    """Create a new version of a ruleset.

    Args:
        db: Database session
        ruleset_id: RuleSet UUID
        created_by: User creating the version

    Returns:
        Created RuleSetVersion

    Raises:
        NotFoundError: If ruleset not found
    """
    # Verify ruleset exists
    await get_ruleset(db, ruleset_id)

    # Get next version number
    stmt = select(func.coalesce(func.max(RuleSetVersion.version), 0)).where(
        RuleSetVersion.ruleset_id == ruleset_id
    )
    result = await db.execute(stmt)
    maxv = result.scalar_one()
    nextv = int(maxv) + 1

    ruleset_version = RuleSetVersion(
        ruleset_id=str(ruleset_id),
        version=nextv,
        status=EntityStatus.DRAFT,
        created_by=created_by,
    )
    db.add(ruleset_version)
    await db.flush()

    logger.info(
        "Created ruleset version %s (ruleset_id=%s,version=%s)",
        ruleset_version.ruleset_version_id,
        ruleset_id,
        nextv,
    )
    return ruleset_version


async def attach_rules_to_version(
    db: AsyncSession,
    *,
    ruleset_version_id: UUID | str,
    rule_version_ids: list[str],
    modified_by: str,
) -> RuleSetVersion:
    """Attach rule versions to a ruleset version.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        rule_version_ids: List of rule version IDs to attach
        modified_by: User making the change

    Returns:
        Updated RuleSetVersion

    Raises:
        NotFoundError: If ruleset version or rule versions not found
        ConflictError: If rule versions are not approved or have mismatched types
    """
    # Get ruleset version
    version = await get_ruleset_version(db, ruleset_version_id)

    # Get ruleset to check rule_type
    stmt = select(RuleSet).where(RuleSet.ruleset_id == version.ruleset_id)
    result = await db.execute(stmt)
    ruleset = result.scalar_one_or_none()
    if not ruleset:
        raise NotFoundError("Ruleset not found", details={"ruleset_id": str(version.ruleset_id)})

    # Old membership for audit - query directly to avoid lazy loading issues
    old_members_stmt = select(RuleSetVersionRule.rule_version_id).where(
        RuleSetVersionRule.ruleset_version_id == str(ruleset_version_id)
    )
    old_members_result = await db.execute(old_members_stmt)
    old_members = [str(m[0]) for m in old_members_result.all()]

    # Validate and attach each rule version
    for rv_id in rule_version_ids:
        # Check rule version exists
        stmt = select(RuleVersion).where(RuleVersion.rule_version_id == rv_id)
        result = await db.execute(stmt)
        rv = result.scalar_one_or_none()
        if not rv:
            raise NotFoundError("RuleVersion not found", details={"rule_version_id": str(rv_id)})

        # Get parent rule for type check
        stmt = select(Rule).where(Rule.rule_id == rv.rule_id)
        result = await db.execute(stmt)
        rule = result.scalar_one_or_none()
        if not rule:
            raise NotFoundError("Rule not found", details={"rule_id": str(rv.rule_id)})

        # Validate rule type matches
        if rule.rule_type != ruleset.rule_type:
            raise ConflictError(
                f"Rule type mismatch: rule is {rule.rule_type}, ruleset is {ruleset.rule_type}",
                details={
                    "rule_id": str(rv.rule_id),
                    "rule_type": rule.rule_type,
                    "ruleset_type": ruleset.rule_type,
                },
            )

        # Check for existing membership
        exists_stmt = select(RuleSetVersionRule).where(
            RuleSetVersionRule.ruleset_version_id == str(ruleset_version_id),
            RuleSetVersionRule.rule_version_id == rv_id,
        )
        result = await db.execute(exists_stmt)
        existing = result.scalar_one_or_none()
        if existing:
            continue

        # Create membership
        membership = RuleSetVersionRule(
            ruleset_version_id=str(ruleset_version_id),
            rule_version_id=rv_id,
        )
        db.add(membership)

    await db.flush()

    # New membership for audit - query directly to avoid lazy loading issues
    new_members_stmt = select(RuleSetVersionRule.rule_version_id).where(
        RuleSetVersionRule.ruleset_version_id == str(ruleset_version_id)
    )
    new_members_result = await db.execute(new_members_stmt)
    new_members = [str(m[0]) for m in new_members_result.all()]

    # Audit entry
    await create_audit_log_async(
        db,
        entity_type="RULESET_VERSION",
        entity_id=str(ruleset_version_id),
        action="ATTACH_RULES",
        old_value={"rule_version_ids": old_members},
        new_value={"rule_version_ids": new_members},
        performed_by=modified_by,
    )

    logger.info("Attached %d rules to version %s", len(new_members), ruleset_version_id)
    return version


async def submit_ruleset_version(
    db: AsyncSession,
    *,
    ruleset_version_id: UUID | str,
    maker: str,
    idempotency_key: str | None = None,
) -> RuleSetVersion:
    """Submit a ruleset version for approval.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        maker: User submitting
        idempotency_key: Optional idempotency key

    Returns:
        Submitted RuleSetVersion

    Raises:
        NotFoundError: If version not found
        ConflictError: If version not in DRAFT/REJECTED state
    """
    version = await get_ruleset_version(db, ruleset_version_id)

    # Check for idempotency
    if idempotency_key:
        existing_stmt = select(Approval).where(
            Approval.entity_type == "RULESET_VERSION",
            Approval.entity_id == version.ruleset_version_id,
            Approval.idempotency_key == idempotency_key,
        )
        result = await db.execute(existing_stmt)
        existing_approval = result.scalar_one_or_none()
        if existing_approval:
            logger.info(
                "Idempotent submit detected for version %s with key %s",
                ruleset_version_id,
                idempotency_key,
            )
            return version

    if version.status not in (EntityStatus.DRAFT, EntityStatus.REJECTED):
        raise ConflictError(
            f"Only DRAFT or REJECTED versions can be submitted (current: {version.status})",
            details={"status": version.status},
        )

    old_value = {
        **snapshot_entity(version, include=["status"]),
        "rule_version_ids": await _ruleset_version_member_ids(db, version.ruleset_version_id),
    }

    version.status = EntityStatus.PENDING_APPROVAL
    await db.flush()

    approval = Approval(
        entity_type="RULESET_VERSION",
        entity_id=version.ruleset_version_id,
        action="SUBMIT",
        maker=maker,
        status="PENDING",
        idempotency_key=idempotency_key,
    )
    db.add(approval)
    await db.flush()

    await create_audit_log_async(
        db,
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        action="SUBMIT",
        old_value=old_value,
        new_value={
            **snapshot_entity(version, include=["status"]),
            "rule_version_ids": await _ruleset_version_member_ids(db, version.ruleset_version_id),
        },
        performed_by=maker,
    )

    # Get ruleset for notification
    stmt = select(RuleSet).where(RuleSet.ruleset_id == version.ruleset_id)
    result = await db.execute(stmt)
    ruleset = result.scalar_one_or_none()

    notify(
        "RULESET_VERSION_SUBMITTED",
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        actor=maker,
        details={
            "ruleset_id": str(version.ruleset_id),
            "version": version.version,
            "rule_type": ruleset.rule_type if ruleset else None,
        },
    )

    logger.info("Submitted ruleset version %s by %s", version.ruleset_version_id, maker)
    return version


async def approve_ruleset_version(
    db: AsyncSession, *, ruleset_version_id: UUID | str, checker: str
) -> RuleSetVersion:
    """Approve a ruleset version (triggers publishing).

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        checker: User approving

    Returns:
        Approved RuleSetVersion

    Raises:
        NotFoundError: If version or approval not found
        MakerCheckerViolation: If maker == checker
        CompilationError: If publishing fails
    """
    approval = await get_pending_approval(db, entity_id=ruleset_version_id)
    if not approval:
        raise NotFoundError(
            "Pending approval not found", details={"ruleset_version_id": str(ruleset_version_id)}
        )

    check_maker_not_checker(approval.maker, checker)

    version = await get_ruleset_version(db, ruleset_version_id)
    ruleset = await _get_ruleset(db, version.ruleset_id)

    old_value = {
        **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
        "rule_version_ids": await _ruleset_version_member_ids(db, version.ruleset_version_id),
    }

    now = datetime.now(UTC)

    await _auto_approve_rule_versions(db, version, checker, now)
    await _supersede_previous_ruleset_versions(db, version)

    version.status = EntityStatus.APPROVED
    version.approved_by = checker
    version.approved_at = now

    await update_approval_approved(db, approval, checker)

    manifest_id = await _publish_ruleset_artifact(db, version, ruleset, checker)

    await create_approval_audit_log(
        db,
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        checker=checker,
        old_value=old_value,
        new_value={
            **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
            "rule_version_ids": await _ruleset_version_member_ids(db, version.ruleset_version_id),
            "manifest_id": manifest_id,
        },
    )

    await db.flush()

    notify(
        "RULESET_VERSION_APPROVED",
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        actor=checker,
        details={
            "ruleset_id": str(version.ruleset_id),
            "version": version.version,
            "rule_type": ruleset.rule_type,
        },
    )

    logger.info("Approved ruleset version %s by %s", version.ruleset_version_id, checker)
    return version


async def reject_ruleset_version(
    db: AsyncSession, *, ruleset_version_id: UUID | str, checker: str, remarks: str | None = None
) -> RuleSetVersion:
    """Reject a ruleset version.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        checker: User rejecting
        remarks: Optional rejection remarks

    Returns:
        Rejected RuleSetVersion

    Raises:
        NotFoundError: If version or approval not found
        MakerCheckerViolation: If maker == checker
    """
    approval = await get_pending_approval(db, entity_id=ruleset_version_id)
    if not approval:
        raise NotFoundError(
            "Pending approval not found", details={"ruleset_version_id": str(ruleset_version_id)}
        )

    if approval.maker == checker:
        raise MakerCheckerViolation("Maker cannot reject their own submission")

    version = await get_ruleset_version(db, ruleset_version_id)

    old_value = {
        **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
        "rule_version_ids": await _ruleset_version_member_ids(db, version.ruleset_version_id),
    }

    now = datetime.now(UTC)
    version.status = EntityStatus.REJECTED

    approval.checker = checker
    approval.status = "REJECTED"
    approval.decided_at = now
    if remarks:
        approval.remarks = remarks

    await create_audit_log_async(
        db,
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        action="REJECT",
        old_value=old_value,
        new_value={
            **snapshot_entity(version, include=["status", "approved_by", "approved_at"]),
            "rule_version_ids": await _ruleset_version_member_ids(db, version.ruleset_version_id),
        },
        performed_by=checker,
    )
    await db.flush()

    notify(
        "RULESET_VERSION_REJECTED",
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        actor=checker,
        details={"version": version.version},
    )

    logger.info("Rejected ruleset version %s by %s", version.ruleset_version_id, checker)
    return version


async def activate_ruleset_version(
    db: AsyncSession, *, ruleset_version_id: UUID | str, activated_by: str
) -> RuleSetVersion:
    """Activate a ruleset version.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        activated_by: User activating

    Returns:
        Activated RuleSetVersion

    Raises:
        NotFoundError: If version not found
        ConflictError: If version not APPROVED
    """
    version = await get_ruleset_version(db, ruleset_version_id)

    if version.status != EntityStatus.APPROVED:
        raise ConflictError(
            f"Only APPROVED versions can be activated (current: {version.status})",
            details={"status": version.status},
        )

    old_value = snapshot_entity(version, include=["status", "activated_at"])

    prev_stmt = select(RuleSetVersion).where(
        RuleSetVersion.ruleset_id == version.ruleset_id,
        RuleSetVersion.ruleset_version_id != version.ruleset_version_id,
        RuleSetVersion.status == EntityStatus.ACTIVE,
    )
    result = await db.execute(prev_stmt)
    prev_versions = result.scalars().all()
    for pv in prev_versions:
        pv.status = EntityStatus.SUPERSEDED

    version.status = EntityStatus.ACTIVE
    version.activated_at = datetime.now(UTC)
    await db.flush()

    new_value = snapshot_entity(version, include=["status", "activated_at"])

    await create_audit_log_async(
        db,
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        action="ACTIVATE",
        old_value=old_value,
        new_value=new_value,
        performed_by=activated_by,
    )

    notify(
        "RULESET_VERSION_ACTIVATED",
        entity_type="RULESET_VERSION",
        entity_id=str(version.ruleset_version_id),
        actor=activated_by,
        details={
            "ruleset_id": str(version.ruleset_id),
            "version": version.version,
        },
    )

    logger.info("Activated ruleset version %s", version.ruleset_version_id)
    return version


async def compile_ruleset_version(
    db: AsyncSession, *, ruleset_version_id: UUID | str, invoked_by: str
) -> dict:
    """Compile a ruleset version to AST (in-memory only, not stored).

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID
        invoked_by: User invoking compilation

    Returns:
        Dictionary with ruleset_version_id, compiled_ast, checksum, can_publish, warnings

    Raises:
        NotFoundError: If version not found
        CompilationError: If compilation fails
    """
    version = await get_ruleset_version(db, ruleset_version_id)
    ruleset_stmt = select(RuleSet).where(RuleSet.ruleset_id == version.ruleset_id)
    result = await db.execute(ruleset_stmt)
    ruleset = result.scalar_one_or_none()
    if not ruleset:
        raise NotFoundError("Ruleset not found", details={"ruleset_id": str(version.ruleset_id)})

    # Get rule versions with eager-loaded rules to avoid N+1
    from sqlalchemy.orm import joinedload

    stmt = (
        select(RuleVersion)
        .options(joinedload(RuleVersion.rule))  # Eager load to avoid N+1
        .join(RuleSetVersionRule, RuleSetVersionRule.rule_version_id == RuleVersion.rule_version_id)
        .where(RuleSetVersionRule.ruleset_version_id == version.ruleset_version_id)
        .order_by(RuleVersion.priority.desc())
    )
    result = await db.execute(stmt)
    rule_versions = result.unique().scalars().all()

    if not rule_versions:
        raise CompilationError(
            "Cannot compile ruleset version with no rules attached",
            details={"ruleset_version_id": str(ruleset_version_id)},
        )

    # Build rule data for compiler
    rule_data = []
    for rv in rule_versions:
        # Rule already loaded via joinedload
        rule = rv.rule
        rule_data.append(
            {
                "rule_version_id": str(rv.rule_version_id),
                "rule_id": str(rv.rule_id),
                "rule_name": rule.rule_name if rule else "",
                "rule_type": rule.rule_type if rule else ruleset.rule_type,
                "priority": rv.priority,
                "scope": rv.scope,
                "condition_tree": rv.condition_tree,
            }
        )

    # Compile
    try:
        compiled_ast = await compile_ruleset_ast(str(ruleset.ruleset_id), db)
    except Exception as e:
        logger.error(
            f"Compilation failed for ruleset version {ruleset_version_id}: {e}", exc_info=True
        )
        raise CompilationError(
            f"Compilation failed: {e}",
            details={"ruleset_version_id": str(ruleset_version_id)},
        ) from e

    # Calculate checksum
    import hashlib
    import json

    ast_json = json.dumps(compiled_ast, sort_keys=True, separators=(",", ":"))
    checksum = "sha256:" + hashlib.sha256(ast_json.encode()).hexdigest()

    # Check if all rules are approved
    can_publish = all(rv.status == EntityStatus.APPROVED for rv in rule_versions)

    warnings = []
    if not can_publish:
        warnings.append("Some rules are not approved - publish will auto-approve them")

    logger.info("Compiled ruleset version %s by %s", ruleset_version_id, invoked_by)

    return {
        "ruleset_version_id": str(version.ruleset_version_id),
        "compiled_ast": compiled_ast,
        "checksum": checksum,
        "can_publish": can_publish,
        "warnings": warnings,
    }


# =============================================================================
# Legacy Functions (for backward compatibility during migration)
# =============================================================================


async def get_compiled_ast(db: AsyncSession, ruleset_id: UUID | str) -> dict:
    """Legacy function - use compile_ruleset_version instead."""
    raise NotImplementedError(
        "get_compiled_ast is deprecated. Use compile_ruleset_version with ruleset_version_id."
    )
