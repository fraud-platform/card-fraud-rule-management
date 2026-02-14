"""
Ruleset Publisher Service

Handles publishing of compiled ruleset artifacts to S3-compatible storage
and tracking of published artifacts via the ruleset_manifest table.

Publishing is atomic with RuleSetVersion approval - if publishing fails,
the approval is rolled back and no partial state is committed.

Source-of-truth model (locked):
- DB `ruleset_manifest` is the governance source of truth (approvals/audit/compliance).
- S3/MinIO `manifest.json` is the runtime source of truth (runtime consumption).
- Runtime never reads DB.
- Governance never infers runtime state from S3.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.canonicalizer import to_canonical_json_string
from app.core.config import settings
from app.core.errors import CompilationError, ValidationError
from app.db.models import FieldRegistryManifest, RuleSet, RuleSetManifest, RuleSetVersion

logger = logging.getLogger(__name__)

# Mapping from RuleSet rule_type to runtime ruleset_key
# This is the v1 pragmatic mapping: rule_type determines the runtime publication boundary
RULE_TYPE_TO_RULESET_KEY = {
    "AUTH": "CARD_AUTH",
    "MONITORING": "CARD_MONITORING",
    # ALLOWLIST and BLOCKLIST are governance-only and don't map to runtime keys
    # They are compiled within their respective AUTH/MONITORING contexts
}


def _map_rule_type_to_ruleset_key(rule_type: str) -> str:
    """
    Map a RuleSet's rule_type to its runtime ruleset_key.

    Args:
        rule_type: The RuleSet's rule_type (ALLOWLIST, BLOCKLIST, AUTH, MONITORING)

    Returns:
        The runtime ruleset_key (CARD_AUTH or CARD_MONITORING)

    Raises:
        ValidationError: If rule_type doesn't map to a runtime ruleset_key
    """
    ruleset_key = RULE_TYPE_TO_RULESET_KEY.get(rule_type)
    if not ruleset_key:
        raise ValidationError(
            f"Rule type '{rule_type}' cannot be published to runtime",
            details={
                "rule_type": rule_type,
                "valid_types": list(RULE_TYPE_TO_RULESET_KEY.keys()),
                "message": "Only AUTH and MONITORING rulesets can be published to runtime",
            },
        )
    return ruleset_key


def _serialize_deterministically(compiled_ast: dict) -> bytes:
    """
    Serialize compiled AST to deterministic JSON bytes.

    Uses the canonicalizer to ensure byte-for-byte identical output
    for the same input, which is critical for checksum validation.

    Args:
        compiled_ast: The compiled AST dictionary from the compiler

    Returns:
        UTF-8 encoded JSON bytes with deterministic ordering
    """
    json_string = to_canonical_json_string(compiled_ast)
    return json_string.encode("utf-8")


def _compute_checksum(data: bytes) -> str:
    """
    Compute SHA-256 checksum of data.

    Args:
        data: Bytes to checksum

    Returns:
        SHA-256 checksum in format: sha256:<lowercase-hex> (64 hex chars after prefix)
    """
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


async def _get_latest_field_registry_version(db: AsyncSession) -> int | None:
    """
    Get the latest field registry version.

    Args:
        db: Database session

    Returns:
        The latest field registry version, or None if no field registry has been published
    """
    stmt = select(func.max(FieldRegistryManifest.registry_version))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_next_version(
    db: AsyncSession, environment: str, region: str, country: str, rule_type: str
) -> int:
    """
    Get the next version number for a ruleset manifest.

    Computes the next version as MAX(existing_version) + 1 for the
    given (environment, region, country, rule_type) combination.

    Args:
        db: Database session
        environment: Environment name (local, test, prod)
        region: Region (APAC, EMEA, INDIA, AMERICAS)
        country: Country code
        rule_type: Rule type

    Returns:
        Next version number (1 if no existing manifests)
    """
    stmt = select(func.coalesce(func.max(RuleSetManifest.ruleset_version), 0)).where(
        RuleSetManifest.environment == environment,
        RuleSetManifest.region == region,
        RuleSetManifest.country == country,
        RuleSetManifest.rule_type == rule_type,
    )
    result = await db.execute(stmt)
    max_version = result.scalar_one()
    return int(max_version) + 1


def _generate_s3_uri(
    environment: str,
    country: str,
    ruleset_key: str,
    ruleset_version: int,
) -> str:
    """
    Generate the S3 URI for a ruleset artifact.

    Args:
        environment: Environment name (dev, test, prod)
        country: Country code (US, IN, GB, etc.)
        ruleset_key: Ruleset key (CARD_AUTH or CARD_MONITORING)
        ruleset_version: Version number

    Returns:
        S3 URI (s3://bucket/key format)
    """
    # Use the prefix pattern from settings
    prefix = settings.ruleset_artifact_prefix
    prefix = (
        prefix.replace("{ENV}", environment)
        .replace("{COUNTRY}", country)
        .replace("{RULESET_KEY}", ruleset_key)
    )

    # Generate filename: ruleset.json (immutable, versioned by directory)
    filename = f"v{ruleset_version}/ruleset.json"

    # Combine into full key
    key = f"{prefix}{filename}".strip("/")

    # Return S3 URI
    return f"s3://{settings.s3_bucket_name}/{key}"


def _generate_file_uri(
    environment: str,
    country: str,
    ruleset_key: str,
    ruleset_version: int,
) -> str:
    """
    Generate the filesystem URI for a ruleset artifact.

    Args:
        environment: Environment name (dev, test, prod)
        country: Country code (US, IN, GB, etc.)
        ruleset_key: Ruleset key (CARD_AUTH or CARD_MONITORING)
        ruleset_version: Version number

    Returns:
        File URI (file://absolute/path format)
    """
    # Use filesystem directory from settings
    base_dir = Path(settings.ruleset_filesystem_dir)

    # Create subdirectories: base_dir/{ENV}/{COUNTRY}/{RULESET_KEY}/v{VERSION}/
    version_dir = base_dir / environment / country / ruleset_key / f"v{ruleset_version}"

    # Generate filename
    filename = "ruleset.json"

    # Full path
    full_path = version_dir / filename

    # Return file:// URI
    absolute_path = full_path.resolve()
    return f"file://{absolute_path}"


class FilesystemBackend:
    """
    Filesystem storage backend for ruleset artifacts.

    Useful for local development without Docker/MinIO.
    Creates artifacts in a local directory structure.
    """

    def publish(
        self,
        data: bytes,
        environment: str,
        country: str,
        ruleset_key: str,
        ruleset_version: int,
    ) -> str:
        """
        Write artifact data to local filesystem.

        Args:
            data: Artifact JSON bytes
            environment: Environment name
            country: Country code
            ruleset_key: Ruleset key
            ruleset_version: Version number

        Returns:
            File URI (file://absolute/path)
        """
        base_dir = Path(settings.ruleset_filesystem_dir)
        # Create versioned directory: {ENV}/{COUNTRY}/{RULESET_KEY}/v{VERSION}/
        version_dir = base_dir / environment / country / ruleset_key / f"v{ruleset_version}"
        version_dir.mkdir(parents=True, exist_ok=True)

        filename = "ruleset.json"
        artifact_path = version_dir / filename

        artifact_path.write_bytes(data)

        logger.info(f"Published artifact to filesystem: {artifact_path} ({len(data)} bytes)")

        return f"file://{artifact_path.resolve()}"


class S3Backend:
    """
    S3-compatible storage backend for ruleset artifacts.

    Supports AWS S3 and S3-compatible services like MinIO.
    Uses boto3 for broad compatibility.
    """

    def __init__(self):
        """Initialize S3 client."""
        self._client = None
        self._initialized = False

    def _get_client(self):
        """Get or create boto3 S3 client."""
        if self._client is None:
            try:
                import boto3

                config = {
                    "service_name": "s3",
                    "region_name": settings.s3_region,
                }

                # Add endpoint URL for MinIO or non-AWS S3
                if settings.s3_endpoint_url:
                    config["endpoint_url"] = settings.s3_endpoint_url

                # Add credentials if provided
                if settings.s3_access_key_id and settings.s3_secret_access_key:
                    config["aws_access_key_id"] = settings.s3_access_key_id
                    config["aws_secret_access_key"] = settings.s3_secret_access_key

                # For MinIO, force path style
                if settings.s3_force_path_style:
                    config["config"] = boto3.session.Config(
                        signature_version="s3v4",
                        s3={"addressing_style": "path"},
                    )

                self._client = boto3.client(**config)
                self._initialized = True

            except ImportError:
                raise ValidationError(
                    "boto3 is required for S3 backend but not installed",
                    details={
                        "backend": "s3",
                        "fix": "Install boto3: uv sync --extra dev",
                    },
                )

        return self._client

    def publish(
        self,
        data: bytes,
        environment: str,
        country: str,
        ruleset_key: str,
        ruleset_version: int,
    ) -> str:
        """
        Upload artifact data to S3-compatible storage.

        Args:
            data: Artifact JSON bytes
            environment: Environment name
            country: Country code
            ruleset_key: Ruleset key
            ruleset_version: Version number

        Returns:
            S3 URI (s3://bucket/key)
        """
        client = self._get_client()

        # Generate key from prefix pattern
        prefix = settings.ruleset_artifact_prefix
        prefix = (
            prefix.replace("{ENV}", environment)
            .replace("{COUNTRY}", country)
            .replace("{RULESET_KEY}", ruleset_key)
        )
        filename = f"v{ruleset_version}/ruleset.json"
        key = f"{prefix}{filename}".strip("/")

        # Upload to S3
        try:
            client.put_object(
                Bucket=settings.s3_bucket_name,
                Key=key,
                Body=data,
                ContentType="application/json",
            )
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise CompilationError(
                "Failed to publish artifact to S3",
                details={
                    "bucket": settings.s3_bucket_name,
                    "key": key,
                    "error": str(e),
                },
            ) from e

        s3_uri = f"s3://{settings.s3_bucket_name}/{key}"

        logger.info(f"Published artifact to S3: {s3_uri} ({len(data)} bytes)")

        return s3_uri


def _generate_manifest_content(
    environment: str,
    ruleset_key: str,
    ruleset_version: int,
    artifact_uri: str,
    checksum: str,
    published_at: datetime,
    country: str,
    region: str,
    field_registry_version: int | None = None,
    schema_version: str = "1.1",
) -> dict[str, Any]:
    """
    Generate the manifest.json content for runtime source-of-truth.

    Args:
        environment: Environment name (dev, test, prod)
        ruleset_key: Ruleset key (CARD_AUTH or CARD_MONITORING)
        ruleset_version: Version number
        artifact_uri: URI to the published artifact
        checksum: SHA-256 checksum of the artifact
        published_at: Timestamp of publication
        country: Country code (US, IN, GB, etc.)
        region: Region (APAC, EMEA, INDIA, AMERICAS)
        field_registry_version: Field registry version used for this ruleset
        schema_version: Manifest schema version (1.1 for country-partitioned paths)

    Returns:
        Manifest dictionary with required fields
    """
    content = {
        "schema_version": schema_version,
        "environment": environment,
        "region": region,
        "country": country,
        "ruleset_key": ruleset_key,
        "ruleset_version": ruleset_version,
        "artifact_uri": artifact_uri,
        "checksum": checksum,
        "published_at": published_at.isoformat() + "Z",
    }
    if field_registry_version is not None:
        content["field_registry_version"] = field_registry_version
    return content


def _get_manifest_uri(environment: str, country: str, ruleset_key: str) -> str:
    """
    Generate the URI for the runtime manifest.json pointer file.

    Args:
        environment: Environment name (dev, test, prod)
        country: Country code (US, IN, GB, etc.)
        ruleset_key: Ruleset key (CARD_AUTH or CARD_MONITORING)

    Returns:
        URI to the manifest.json file (s3://bucket/... or file://...)
    """
    backend = settings.ruleset_artifact_backend.lower()

    if backend == "s3":
        prefix = settings.ruleset_artifact_prefix
        prefix = (
            prefix.replace("{ENV}", environment)
            .replace("{COUNTRY}", country)
            .replace("{RULESET_KEY}", ruleset_key)
        )
        key = f"{prefix}manifest.json".strip("/")
        return f"s3://{settings.s3_bucket_name}/{key}"
    else:
        base_dir = Path(settings.ruleset_filesystem_dir)
        manifest_path = base_dir / environment / country / ruleset_key / "manifest.json"
        return f"file://{manifest_path.resolve()}"


class ManifestWriter:
    """
    Handles writing the runtime manifest.json pointer file.

    This is the runtime source-of-truth that the fraud engine reads
    to determine the active ruleset version.
    """

    def write_manifest(
        self,
        manifest_content: dict[str, Any],
        environment: str,
        country: str,
        ruleset_key: str,
    ) -> str:
        """
        Write manifest.json to storage.

        Args:
            manifest_content: The manifest dictionary
            environment: Environment name
            country: Country code
            ruleset_key: Ruleset key

        Returns:
            URI to the written manifest file
        """
        backend = settings.ruleset_artifact_backend.lower()
        manifest_uri = _get_manifest_uri(environment, country, ruleset_key)

        if backend == "s3":
            self._write_manifest_to_s3(manifest_content, manifest_uri)
        else:
            self._write_manifest_to_filesystem(manifest_content, manifest_uri)

        logger.info(f"Wrote runtime manifest: {manifest_uri}")
        return manifest_uri

    def _write_manifest_to_s3(self, manifest_content: dict[str, Any], manifest_uri: str) -> None:
        """Write manifest.json to S3-compatible storage."""
        client = S3Backend()._get_client()

        # Extract key from URI
        bucket = settings.s3_bucket_name
        key = manifest_uri.replace(f"s3://{bucket}/", "")

        # Serialize to JSON bytes
        json_content = json.dumps(manifest_content, sort_keys=True).encode("utf-8")

        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=json_content,
                ContentType="application/json",
            )
        except Exception as e:
            logger.error(f"S3 manifest write failed: {e}")
            raise CompilationError(
                "Failed to write manifest to S3",
                details={
                    "bucket": bucket,
                    "key": key,
                    "error": str(e),
                },
            ) from e

    def _write_manifest_to_filesystem(
        self, manifest_content: dict[str, Any], manifest_uri: str
    ) -> None:
        """Write manifest.json to local filesystem."""
        # Extract path from URI (file://C:\path or file:///path)
        path_str = manifest_uri.replace("file://", "")
        manifest_path = Path(path_str)

        # Ensure directory exists
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON with sorted keys for determinism
        json_content = json.dumps(manifest_content, sort_keys=True, indent=2)
        manifest_path.write_text(json_content, encoding="utf-8")


async def publish_ruleset_version(
    db: AsyncSession,
    ruleset_version: RuleSetVersion,
    ruleset: RuleSet,
    compiled_ast: dict,
    checker: str,
) -> RuleSetManifest:
    """
    Publish a compiled ruleset version artifact to storage and record manifest.

    This function is called atomically within the RuleSetVersion approval transaction.
    If publishing fails, the entire approval transaction is rolled back.

    Publishing flow (operational safety rule):
    1. Serialize and compute checksum
    2. Get next version number
    3. Upload artifact to storage (FIRST - immutable)
    4. Insert manifest row (DB governance audit)
    5. Write/update runtime manifest.json (LAST - only mutable object)

    Args:
        db: Database session (must be in a transaction)
        ruleset_version: The RuleSetVersion being approved
        ruleset: The parent RuleSet (for environment, region, country, rule_type)
        compiled_ast: The compiled AST dictionary
        checker: The user performing the approval

    Returns:
        RuleSetManifest row that was created

    Raises:
        ValidationError: If rule_type cannot be mapped to a ruleset_key
        CompilationError: If publishing to storage fails
    """
    # Step 1: Map rule_type to ruleset_key
    ruleset_key = _map_rule_type_to_ruleset_key(ruleset.rule_type)
    environment = settings.publish_environment

    # Step 2: Serialize deterministically and compute checksum
    artifact_bytes = _serialize_deterministically(compiled_ast)
    checksum = _compute_checksum(artifact_bytes)

    # Step 3: Get next version (this is a SELECT, safe to do before upload)
    ruleset_version_num = await _get_next_version(
        db, environment, ruleset.region, ruleset.country, ruleset.rule_type
    )

    # Step 4: Get the latest field registry version
    field_registry_version = await _get_latest_field_registry_version(db)

    # Step 5: Publish to storage backend FIRST (before any DB writes)
    # This ensures no manifest row exists unless upload succeeded
    # Orphan artifact is harmless; orphan manifest is dangerous
    backend = settings.ruleset_artifact_backend.lower()

    if backend == "s3":
        s3_backend = S3Backend()
        artifact_uri = s3_backend.publish(
            data=artifact_bytes,
            environment=environment,
            country=ruleset.country,
            ruleset_key=ruleset_key,
            ruleset_version=ruleset_version_num,
        )
    elif backend == "filesystem":
        fs_backend = FilesystemBackend()
        artifact_uri = fs_backend.publish(
            data=artifact_bytes,
            environment=environment,
            country=ruleset.country,
            ruleset_key=ruleset_key,
            ruleset_version=ruleset_version_num,
        )
    else:
        raise ValidationError(
            f"Unknown artifact backend: {backend}",
            details={"backend": backend, "valid_backends": ["filesystem", "s3"]},
        )

    # Step 6: Insert manifest row with complete data
    # Single INSERT, no UPDATE needed
    # If upload succeeded but insert fails, artifact is orphaned (harmless, not dangerous)
    published_at = datetime.now(UTC)
    manifest = RuleSetManifest(
        ruleset_manifest_id=str(uuid.uuid7()),
        environment=environment,
        region=ruleset.region,
        country=ruleset.country,
        rule_type=ruleset.rule_type,
        ruleset_version=ruleset_version_num,
        ruleset_version_id=str(ruleset_version.ruleset_version_id),
        field_registry_version=field_registry_version,
        artifact_uri=artifact_uri,
        checksum=checksum,
        created_at=published_at,
        created_by=checker,
    )

    db.add(manifest)
    await db.flush()

    # Step 7: Write/update runtime manifest.json (the ONLY mutable object)
    # This must be done LAST to ensure runtime only sees valid artifacts
    manifest_content = _generate_manifest_content(
        environment=environment,
        ruleset_key=ruleset_key,
        ruleset_version=ruleset_version_num,
        artifact_uri=artifact_uri,
        checksum=checksum,
        published_at=published_at,
        country=ruleset.country,
        region=ruleset.region,
        field_registry_version=field_registry_version,
        schema_version="1.1",
    )
    manifest_writer = ManifestWriter()
    manifest_writer.write_manifest(manifest_content, environment, ruleset.country, ruleset_key)

    logger.info(
        f"Published ruleset version {ruleset_version.ruleset_version_id} as {ruleset_key} "
        f"v{ruleset_version_num} in {environment} by {checker}"
    )

    return manifest
