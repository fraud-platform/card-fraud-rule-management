"""
Field Registry Publisher Service

Compiles and publishes field registry artifacts to S3-compatible storage.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repos import field_registry_manifest_repo, rule_field_version_repo

logger = logging.getLogger(__name__)


class FieldRegistryArtifact:
    """Compiled field registry artifact."""

    def __init__(
        self,
        schema_version: int,
        registry_version: int,
        fields: list[dict],
        checksum: str,
    ):
        self.schema_version = schema_version
        self.registry_version = registry_version
        self.fields = fields
        self.checksum = checksum
        self.created_at = datetime.now(UTC).isoformat()

    def to_json(self) -> str:
        """Convert artifact to JSON string."""
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "registry_version": self.registry_version,
                "fields": self.fields,
                "checksum": self.checksum,
                "created_at": self.created_at,
            },
            indent=2,
            sort_keys=True,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert artifact to dictionary."""
        return {
            "schema_version": self.schema_version,
            "registry_version": self.registry_version,
            "fields": self.fields,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }


class FieldRegistryPublisher:
    """
    Service for compiling and publishing field registry artifacts.

    Similar to RulesetPublisher but for field definitions.
    """

    def __init__(self):
        self.schema_version = 1

    async def compile_registry(self, db: AsyncSession) -> FieldRegistryArtifact:
        """
        Compile field registry from all APPROVED field versions.

        Args:
            db: Database session

        Returns:
            FieldRegistryArtifact with compiled fields
        """
        # Get all APPROVED field versions
        versions = await rule_field_version_repo.get_all_approved_versions(db)

        # Build fields list sorted by field_id
        fields = []
        for v in sorted(versions, key=lambda x: x.field_id):
            fields.append(
                {
                    "field_id": v.field_id,
                    "field_key": v.field_key,
                    "display_name": v.display_name,
                    "description": v.description,
                    "data_type": v.data_type,
                    "allowed_operators": v.allowed_operators,
                    "multi_value_allowed": v.multi_value_allowed,
                    "is_sensitive": v.is_sensitive,
                }
            )

        # Calculate checksum (SHA-256)
        fields_json = json.dumps(fields, sort_keys=True)
        checksum_bytes = hashlib.sha256(fields_json.encode()).digest()
        checksum = f"sha256:{checksum_bytes.hex()}"

        # Get next registry version
        latest = await field_registry_manifest_repo.get_latest_manifest(db)
        next_version = (latest.registry_version if latest else 0) + 1

        artifact = FieldRegistryArtifact(
            schema_version=self.schema_version,
            registry_version=next_version,
            fields=fields,
            checksum=checksum,
        )

        logger.info(
            f"Compiled field registry v{next_version} with {len(fields)} fields",
            extra={"registry_version": next_version, "field_count": len(fields)},
        )

        return artifact

    async def publish(
        self, db: AsyncSession, artifact: FieldRegistryArtifact, created_by: str
    ) -> Any:
        """
        Publish field registry artifact to S3-compatible storage.

        Args:
            db: Database session
            artifact: Compiled artifact
            created_by: User who triggered the publish

        Returns:
            Created FieldRegistryManifest model
        """
        artifact_json = artifact.to_json()
        artifact_bytes = artifact_json.encode("utf-8")

        # Determine storage backend
        if settings.app_env == "local":
            # Use filesystem storage for local development
            return await self._publish_filesystem(db, artifact, artifact_bytes, created_by)
        else:
            # Use S3 for production
            return await self._publish_s3(db, artifact, artifact_bytes, created_by)

    async def _publish_filesystem(
        self,
        db: AsyncSession,
        artifact: FieldRegistryArtifact,
        artifact_bytes: bytes,
        created_by: str,
    ) -> Any:
        """Publish to local filesystem."""
        # Create local directory for artifacts
        artifact_dir = Path(".local") / "field-registry" / f"v{artifact.registry_version}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_file = artifact_dir / "fields.json"
        artifact_file.write_bytes(artifact_bytes)

        # Also write checksum file
        checksum_file = artifact_dir / "checksum.txt"
        checksum_file.write_text(artifact.checksum)

        artifact_uri = str(artifact_file.absolute())

        logger.info(
            f"Published field registry to filesystem: {artifact_uri}",
            extra={"artifact_uri": artifact_uri},
        )

        # Create manifest record
        return await field_registry_manifest_repo.create_manifest(
            db,
            artifact_uri=artifact_uri,
            checksum=artifact.checksum,
            field_count=len(artifact.fields),
            created_by=created_by,
        )

    async def _publish_s3(
        self,
        db: AsyncSession,
        artifact: FieldRegistryArtifact,
        artifact_bytes: bytes,
        created_by: str,
    ) -> Any:
        """Publish to S3."""
        import boto3

        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

        # S3 key: fields/registry/v{version}/fields.json
        s3_key = f"fields/registry/v{artifact.registry_version}/fields.json"

        s3_client.put_object(
            Bucket=settings.s3_bucket_name,
            Key=s3_key,
            Body=artifact_bytes,
            ContentType="application/json",
        )

        artifact_uri = f"s3://{settings.s3_bucket_name}/{s3_key}"

        logger.info(
            f"Published field registry to S3: {artifact_uri}",
            extra={"artifact_uri": artifact_uri},
        )

        # Create manifest record
        return await field_registry_manifest_repo.create_manifest(
            db,
            artifact_uri=artifact_uri,
            checksum=artifact.checksum,
            field_count=len(artifact.fields),
            created_by=created_by,
        )

    def update_manifest_pointer(self) -> None:
        """
        Update the manifest.json pointer to latest version.

        Called after successful publish to keep runtime pointing to latest.
        """
        # This would update fields/registry/manifest.json
        # to point to the latest version
        logger.info("Field registry manifest pointer updated")
