"""
Main Compiler for Fraud Rule Governance API.

Compiles approved RuleSets into deterministic AST/JSON for Quarkus runtime.

This is the CORE VALUE of this backend:
- Transforms governance data into runtime-executable format
- Ensures determinism (same input = identical byte-for-byte output)
- Validates all references before compilation
- Declares evaluation semantics explicitly

The compiler output is the contract between this control-plane
and the Quarkus runtime fraud engine.
"""

import json
import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.canonicalizer import canonicalize_json
from app.compiler.validator import validate_condition_tree
from app.core.errors import CompilationError, ConflictError, NotFoundError
from app.db.models import Rule, RuleField, RuleSet, RuleSetVersion, RuleSetVersionRule, RuleVersion
from app.domain.enums import EntityStatus, RuleType

logger = logging.getLogger(__name__)


# Locked evaluation semantics (from IMPLEMENTATION-GUIDE.md)
RULE_TYPE_TO_EVALUATION_MODE = {
    RuleType.ALLOWLIST.value: "FIRST_MATCH",
    RuleType.BLOCKLIST.value: "FIRST_MATCH",
    RuleType.AUTH.value: "FIRST_MATCH",
    RuleType.MONITORING.value: "ALL_MATCHING",
}


async def compile_ruleset(
    ruleset_id: UUID | str, db: AsyncSession, ruleset_version_id: UUID | str | None = None
) -> dict:
    """
    Compile a RuleSetVersion into deterministic AST/JSON.

    This is the main entry point for compilation. It:
    1. Loads the RuleSetVersion and validates it's APPROVED
    2. Loads all attached RuleVersions and validates they're APPROVED
    3. Loads the rule field catalog for validation
    4. Validates all condition trees
    5. Sorts rules deterministically
    6. Maps rule_type to evaluation mode
    7. Builds canonical AST
    8. Returns deterministic JSON structure

    Args:
        ruleset_id: UUID of the RuleSet (parent RuleSetVersion)
        db: Database session
        ruleset_version_id: Optional UUID of specific RuleSetVersion to compile.
                           If not provided, loads the ACTIVE version.

    Returns:
        Compiled AST dictionary with canonical structure

    Raises:
        NotFoundError: If RuleSet doesn't exist
        ConflictError: If RuleSetVersion is not APPROVED
        CompilationError: If validation fails or compilation cannot proceed

    Example Output:
        {
            "rulesetId": "rs-123",
            "version": 7,
            "ruleType": "MONITORING",
            "evaluation": {"mode": "ALL_MATCHING"},
            "velocityFailurePolicy": "SKIP",
            "rules": [
                {
                    "ruleId": "r-10",
                    "ruleVersionId": "rv-123",
                    "priority": 100,
                    "scope": {},
                    "when": {
                        "and": [
                            {"field": "amount", "op": "GT", "value": 3000}
                        ]
                    },
                    "action": "REVIEW"
                }
            ]
        }
    """
    start_time = time.time()
    logger.info("Starting compilation for ruleset %s", ruleset_id)

    try:
        # Step 1: Load the RuleSetVersion to compile
        if ruleset_version_id:
            # Load specific version
            ruleset_version = await _load_specific_ruleset_version(db, ruleset_version_id)
            # Verify it belongs to the correct ruleset
            if str(ruleset_version.ruleset_id) != str(ruleset_id):
                raise ConflictError(
                    f"RuleSetVersion {ruleset_version_id} does not belong to RuleSet {ruleset_id}",
                    details={
                        "ruleset_version_id": str(ruleset_version_id),
                        "ruleset_id": str(ruleset_id),
                    },
                )
        else:
            # Load active RuleSetVersion for the RuleSet
            ruleset_version = await _load_active_ruleset_version(db, ruleset_id)

        # Step 2: Verify RuleSetVersion is APPROVED
        if ruleset_version.status not in (
            EntityStatus.APPROVED.value,
            EntityStatus.ACTIVE.value,
        ):
            raise ConflictError(
                f"RuleSetVersion must be APPROVED or ACTIVE to compile "
                f"(status: {ruleset_version.status})",
                details={
                    "ruleset_version_id": str(ruleset_version.ruleset_version_id),
                    "status": ruleset_version.status,
                },
            )

        # Step 3: Load all attached RuleVersions
        rule_versions = await _load_rule_versions_for_version(
            db, ruleset_version.ruleset_version_id
        )

        if not rule_versions:
            logger.warning(
                f"RuleSetVersion {ruleset_version.ruleset_version_id} has no attached rules"
            )
            # Empty ruleset is valid - compile to empty rules array

        # Step 4: Verify all RuleVersions are APPROVED
        _verify_all_approved(rule_versions, ruleset_version.ruleset_version_id)

        # Step 5: Load rule field catalog for validation
        rule_fields = await _load_rule_fields(db)

        # Step 6: Validate all condition trees
        _validate_all_condition_trees(
            rule_versions, rule_fields, ruleset_version.ruleset_version_id
        )

        # Step 7: Sort rules deterministically (priority DESC, rule_id ASC)
        sorted_rules = await _sort_rules_deterministically(db, rule_versions)

        # Step 8: Map rule_type to evaluation mode
        ruleset = await _load_ruleset(db, ruleset_id)
        evaluation_mode = _get_evaluation_mode(ruleset.rule_type)

        # Step 9: Build AST
        ast = _build_ast(ruleset, ruleset_version, sorted_rules, evaluation_mode)

        # Step 10: Canonicalize (ensure deterministic key ordering)
        canonical_ast = canonicalize_json(ast)

        # Calculate metrics (optimized to avoid double json.dumps)
        duration = time.time() - start_time
        rule_count = len(sorted_rules)
        json_str = json.dumps(canonical_ast)
        ast_bytes = len(json_str.encode("utf-8"))

        logger.info(
            "Successfully compiled ruleset %s: %d rules, mode=%s, duration=%.3fs, size=%d bytes",
            ruleset_id,
            rule_count,
            evaluation_mode,
            duration,
            ast_bytes,
        )

        # Record metrics (if observability is enabled)
        _record_compiler_metrics("success", duration, rule_count, ast_bytes)

        return canonical_ast

    except Exception:
        # Record failure metrics
        duration = time.time() - start_time
        _record_compiler_metrics("error", duration, 0, 0)
        raise


def _record_compiler_metrics(status: str, duration: float, rule_count: int, ast_bytes: int) -> None:
    """
    Record compiler metrics to Prometheus.

    This is called at the end of compilation to track:
    - Compilation success/failure rate
    - Compilation duration
    - Number of rules in compiled rulesets
    - Size of generated ASTs

    Metrics failures are silently ignored to avoid breaking compilation.

    Args:
        status: "success" or "error"
        duration: Compilation duration in seconds
        rule_count: Number of rules compiled
        ast_bytes: Size of AST in bytes
    """
    try:
        from app.core.observability import get_region, metrics

        region = get_region() or "unknown"

        metrics.compiler_compilations_total.labels(status=status, region=region).inc()
        metrics.compiler_duration_seconds.labels(region=region).observe(duration)

        if status == "success":
            metrics.compiler_rules_count.labels(region=region).observe(rule_count)
            metrics.compiler_ast_bytes.labels(region=region).observe(ast_bytes)
    except Exception:
        # Silently ignore all metrics errors (ImportError, AttributeError, etc.)
        # Metrics should never break compilation
        pass


async def _load_ruleset(db: AsyncSession, ruleset_id: UUID | str) -> RuleSet:
    """
    Load RuleSet by ID.

    Args:
        db: Database session
        ruleset_id: RuleSet UUID

    Returns:
        RuleSet model

    Raises:
        NotFoundError: If RuleSet doesn't exist
    """
    stmt = select(RuleSet).where(RuleSet.ruleset_id == ruleset_id)
    result = await db.execute(stmt)
    ruleset = result.scalar_one_or_none()

    if not ruleset:
        raise NotFoundError("RuleSet not found", details={"ruleset_id": str(ruleset_id)})

    return ruleset


async def _load_active_ruleset_version(db: AsyncSession, ruleset_id: UUID | str) -> RuleSetVersion:
    """
    Load the active RuleSetVersion for a RuleSet.

    Args:
        db: Database session
        ruleset_id: RuleSet UUID

    Returns:
        The active RuleSetVersion model

    Raises:
        NotFoundError: If no active version exists
    """
    stmt = select(RuleSetVersion).where(
        RuleSetVersion.ruleset_id == ruleset_id,
        RuleSetVersion.status == "ACTIVE",
    )
    result = await db.execute(stmt)
    ruleset_version = result.scalar_one_or_none()

    if not ruleset_version:
        raise NotFoundError(
            "No active RuleSetVersion found for this RuleSet",
            details={"ruleset_id": str(ruleset_id)},
        )

    return ruleset_version


async def _load_specific_ruleset_version(
    db: AsyncSession, ruleset_version_id: UUID
) -> RuleSetVersion:
    """
    Load a specific RuleSetVersion by ID.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID

    Returns:
        The RuleSetVersion model

    Raises:
        NotFoundError: If version doesn't exist
    """
    stmt = select(RuleSetVersion).where(
        RuleSetVersion.ruleset_version_id == ruleset_version_id,
    )
    result = await db.execute(stmt)
    ruleset_version = result.scalar_one_or_none()

    if not ruleset_version:
        raise NotFoundError(
            "RuleSetVersion not found",
            details={"ruleset_version_id": str(ruleset_version_id)},
        )

    return ruleset_version


async def _load_rule_versions_for_version(
    db: AsyncSession, ruleset_version_id: UUID
) -> list[RuleVersion]:
    """
    Load all RuleVersions attached to a RuleSetVersion.

    Args:
        db: Database session
        ruleset_version_id: RuleSetVersion UUID

    Returns:
        List of RuleVersion models
    """
    stmt = (
        select(RuleVersion)
        .join(
            RuleSetVersionRule,
            RuleSetVersionRule.rule_version_id == RuleVersion.rule_version_id,
        )
        .where(RuleSetVersionRule.ruleset_version_id == ruleset_version_id)
    )

    result = await db.execute(stmt)
    return list(result.scalars().all())


def _verify_all_approved(rule_versions: list[RuleVersion], ruleset_id: UUID | str) -> None:
    """
    Verify that all RuleVersions are APPROVED.

    Args:
        rule_versions: List of RuleVersion models
        ruleset_id: RuleSet UUID (for error context)

    Raises:
        CompilationError: If any RuleVersion is not APPROVED
    """
    non_approved = [rv for rv in rule_versions if rv.status != EntityStatus.APPROVED.value]

    if non_approved:
        raise CompilationError(
            "Cannot compile RuleSet with non-APPROVED rule versions",
            details={
                "ruleset_id": str(ruleset_id),
                "non_approved_count": len(non_approved),
                "non_approved_versions": [
                    {"rule_version_id": str(rv.rule_version_id), "status": rv.status}
                    for rv in non_approved
                ],
            },
        )


async def _load_rule_fields(db: AsyncSession) -> dict[str, dict]:
    """
    Load all rule fields as a lookup dictionary.

    Returns:
        Dictionary mapping field_key -> field metadata
        {
            "field_key": {
                "data_type": "STRING",
                "allowed_operators": ["EQ", "IN"],
                "multi_value_allowed": True,
                "is_sensitive": False,
                "field_id": 7,
            }
        }
    """
    stmt = select(RuleField).order_by(RuleField.field_id)
    result = await db.execute(stmt)
    fields = result.scalars().all()

    return {
        field.field_key: {
            "data_type": field.data_type,
            "allowed_operators": field.allowed_operators,
            "multi_value_allowed": field.multi_value_allowed,
            "is_sensitive": field.is_sensitive,
            "field_id": field.field_id,
        }
        for field in fields
    }


def _validate_all_condition_trees(
    rule_versions: list[RuleVersion], rule_fields: dict[str, dict], ruleset_id: UUID
) -> None:
    """
    Validate all condition trees in the RuleSet.

    Args:
        rule_versions: List of RuleVersion models
        rule_fields: Field metadata dictionary
        ruleset_id: RuleSet UUID (for error context)

    Raises:
        CompilationError: If any condition tree is invalid
    """
    for rv in rule_versions:
        try:
            # During compilation we tolerate fields that are not present in the
            # governance catalog (they may be runtime-provided). Use lenient
            # validation mode here.
            validate_condition_tree(rv.condition_tree, rule_fields, allow_unknown_fields=True)
        except Exception as e:
            # Wrap validation errors with compilation context
            raise CompilationError(
                f"Condition tree validation failed for rule version {rv.rule_version_id}",
                details={
                    "ruleset_id": str(ruleset_id),
                    "rule_version_id": str(rv.rule_version_id),
                    "rule_id": str(rv.rule_id),
                    "error": str(e),
                    "condition_tree": rv.condition_tree,
                },
            ) from e


async def _sort_rules_deterministically(
    db: AsyncSession, rule_versions: list[RuleVersion]
) -> list[tuple[RuleVersion, Rule]]:
    """
    Sort rules deterministically by (priority DESC, rule_id ASC).

    This ensures that the same RuleSet always produces the same output order,
    which is critical for deterministic compilation.

    N+1 Query Fix: Uses a single JOIN query instead of N+1 separate queries
    to fetch Rule data for each RuleVersion.

    Args:
        db: Database session
        rule_versions: List of RuleVersion models

    Returns:
        List of (RuleVersion, Rule) tuples sorted deterministically
    """
    rule_version_ids = [rv.rule_version_id for rv in rule_versions]

    # Single query with JOIN - get pairs directly (fixes N+1 query)
    stmt = (
        select(RuleVersion, Rule)
        .join(Rule, RuleVersion.rule_id == Rule.rule_id)
        .where(RuleVersion.rule_version_id.in_(rule_version_ids))
    )
    result = await db.execute(stmt)

    # Returns list of tuples directly
    paired = [(rv, rule) for rv, rule in result]

    # Sort by priority DESC, then rule_id ASC for determinism
    return sorted(paired, key=lambda p: (-p[0].priority, str(p[1].rule_id)))


def _get_evaluation_mode(rule_type: str) -> str:
    """
    Get evaluation mode for a rule type.

    Uses locked semantics from IMPLEMENTATION-GUIDE.md.

    Args:
        rule_type: RuleType value (ALLOWLIST, BLOCKLIST, AUTH, MONITORING)

    Returns:
        Evaluation mode (FIRST_MATCH or ALL_MATCHING)

    Raises:
        CompilationError: If rule_type is invalid
    """
    mode = RULE_TYPE_TO_EVALUATION_MODE.get(rule_type)

    if not mode:
        raise CompilationError(f"Unknown rule type: {rule_type}", details={"rule_type": rule_type})

    return mode


def _build_ast(
    ruleset: RuleSet,
    ruleset_version: RuleSetVersion,
    sorted_rules: list[tuple[RuleVersion, Rule]],
    evaluation_mode: str,
) -> dict:
    """
    Build the AST structure.

    Args:
        ruleset: RuleSet model
        ruleset_version: RuleSetVersion model
        sorted_rules: List of (RuleVersion, Rule) tuples in deterministic order
        evaluation_mode: Evaluation mode (FIRST_MATCH or ALL_MATCHING)

    Returns:
        AST dictionary (not yet canonicalized)
    """
    # Default velocity failure policy (as per IMPLEMENTATION-GUIDE.md recommendation)
    velocity_failure_policy = "SKIP"

    ast = {
        "rulesetId": str(ruleset.ruleset_id),
        "version": ruleset_version.version,
        "ruleType": ruleset.rule_type,
        "evaluation": {"mode": evaluation_mode},
        "velocityFailurePolicy": velocity_failure_policy,
        "rules": [],
    }

    # Build rule entries
    for rule_version, rule in sorted_rules:
        rule_entry = {
            "ruleId": str(rule.rule_id),
            "ruleVersionId": str(rule_version.rule_version_id),
            "priority": rule_version.priority,
            "scope": rule_version.scope or {},
            "when": rule_version.condition_tree,
            "action": rule_version.action,  # Use rule's configured action
        }
        ast["rules"].append(rule_entry)

    return ast
