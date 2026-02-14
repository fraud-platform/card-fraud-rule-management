"""
End-to-end tests for the Ruleset Publisher with MinIO.

These tests verify the full publish flow:
1. Create RuleSet with rule versions
2. Submit for approval
3. Approve (triggers automatic publishing)
4. Verify artifact in S3/MinIO
5. Verify manifest row in database
6. Verify runtime manifest.json in S3/MinIO

Requires:
- Local PostgreSQL running
- Local MinIO running (or configured S3)
- Doppler secrets configured
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import (
    Rule,
    RuleSetManifest,
    RuleVersion,
)
from app.domain.enums import EntityStatus, RuleType
from app.repos.ruleset_repo import (
    approve_ruleset_version,
    attach_rules_to_version,
    create_ruleset,
    create_ruleset_version,
    submit_ruleset_version,
)

# =============================================================================
# Test Helpers
# =============================================================================


def _get_settings() -> Settings:
    """Get fresh Settings instance (reloads from environment).

    This is needed because the module-level `settings` import may load
    before Doppler injects environment variables. Using this function
    ensures we always get the latest values from environment.
    """
    return Settings()


def _get_s3_config() -> tuple[str, str]:
    """Get S3 bucket name and publish environment from environment.

    Returns (bucket_name, publish_environment) tuple.
    """
    settings = _get_settings()
    return (settings.s3_bucket_name, settings.publish_environment)


def _get_publish_env() -> str:
    """Get publish environment from settings."""
    return _get_settings().publish_environment


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture(scope="function")
def s3_client():
    """Create a boto3 S3 client for verifying uploaded artifacts.

    Uses function scope to ensure fresh credentials from environment on each test.
    """
    import boto3.session

    # Get fresh settings to ensure we have Doppler-injected values
    settings = _get_settings()

    config: dict[str, Any] = {"service_name": "s3", "region_name": settings.s3_region}

    if settings.s3_endpoint_url:
        config["endpoint_url"] = settings.s3_endpoint_url
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        config["aws_access_key_id"] = settings.s3_access_key_id
        config["aws_secret_access_key"] = settings.s3_secret_access_key
    if settings.s3_force_path_style:
        config["config"] = boto3.session.Config(
            signature_version="s3v4", s3={"addressing_style": "path"}
        )

    client = boto3.client(**config)

    # Verify S3/MinIO is available
    try:
        client.head_bucket(Bucket=settings.s3_bucket_name)
    except Exception as e:
        pytest.skip(f"S3/MinIO not available: {e}")

    return client


def _cleanup_test_artifacts(s3_client, ruleset_key: str, country: str = "IN"):
    """Clean up test artifacts from S3."""
    settings = _get_settings()

    try:
        prefix = f"rulesets/{settings.publish_environment}/{country}/{ruleset_key}/"
        response = s3_client.list_objects_v2(Bucket=settings.s3_bucket_name, Prefix=prefix)
        if "Contents" in response:
            for obj in response["Contents"]:
                s3_client.delete_object(Bucket=settings.s3_bucket_name, Key=obj["Key"])
    except Exception:
        pass  # Best effort cleanup


# =============================================================================
# E2e Tests
# =============================================================================


class TestRulesetPublisherE2E:
    """End-to-end tests for ruleset publishing with MinIO."""

    @classmethod
    def setup_class(cls):
        """Skip tests if MinIO/S3 is not available."""
        settings = _get_settings()

        if settings.ruleset_artifact_backend.lower() == "s3":
            import boto3

            config = {"service_name": "s3", "region_name": settings.s3_region}
            if settings.s3_endpoint_url:
                config["endpoint_url"] = settings.s3_endpoint_url
            if settings.s3_access_key_id and settings.s3_secret_access_key:
                config["aws_access_key_id"] = settings.s3_access_key_id
                config["aws_secret_access_key"] = settings.s3_secret_access_key
            if settings.s3_force_path_style:
                config["config"] = boto3.session.Config(
                    signature_version="s3v4", s3={"addressing_style": "path"}
                )

            client = boto3.client(**config)
            try:
                client.head_bucket(Bucket=settings.s3_bucket_name)
            except Exception as e:
                pytest.skip(f"S3/MinIO not available for integration tests: {e}")

    @pytest.mark.anyio
    async def test_publish_AUTH_ruleset_to_minio(
        self, async_db_session, s3_client, cleanup_manifests
    ):
        """Full e2e test: Create, approve, and publish a AUTH RuleSet.

        Verifies:
        - RuleSet is created with rule versions
        - Approval workflow completes
        - Artifact is uploaded to S3/MinIO
        - Manifest row is created in database
        - Artifact content is valid JSON
        - Checksum is correct
        - Runtime manifest.json is written
        """
        # Get fresh settings to ensure we have Doppler-injected values
        settings = _get_settings()
        ruleset_key = "CARD_AUTH"
        _cleanup_test_artifacts(s3_client, ruleset_key, "IN")

        try:
            # Step 1: Create a RuleVersion (must be APPROVED before attaching)
            rule_id = uuid.uuid7()
            rule = Rule(
                rule_id=rule_id,
                rule_name="Test AUTH Rule",
                description="Test rule for publisher e2e",
                rule_type=RuleType.AUTH.value,
                current_version=1,
                status=EntityStatus.DRAFT.value,
                version=1,
                created_by="test-maker",
                created_at=datetime.now(UTC),
            )
            async_db_session.add(rule)
            await async_db_session.flush()

            rule_version = RuleVersion(
                rule_version_id=uuid.uuid7(),
                rule_id=rule_id,
                version=1,
                condition_tree={
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 1000,
                },
                priority=100,
                created_by="test-maker",
                created_at=datetime.now(UTC),
                status=EntityStatus.APPROVED.value,
                approved_by="test-checker",
                approved_at=datetime.now(UTC),
            )
            async_db_session.add(rule_version)
            await async_db_session.flush()

            # Step 2: Create a AUTH RuleSet identity
            ruleset = await create_ruleset(
                async_db_session,
                environment=settings.publish_environment,
                region="APAC",
                country="IN",
                rule_type=RuleType.AUTH.value,
                name="Test AUTH RuleSet",
                description="For publisher e2e test",
                created_by="test-maker",
            )
            await async_db_session.flush()
            ruleset_id = ruleset.ruleset_id

            # Step 3: Create a RuleSetVersion
            ruleset_version = await create_ruleset_version(
                async_db_session,
                ruleset_id=ruleset_id,
                created_by="test-maker",
            )
            await async_db_session.flush()
            ruleset_version_id = ruleset_version.ruleset_version_id

            # Step 4: Attach the rule version to the RuleSetVersion
            await attach_rules_to_version(
                async_db_session,
                ruleset_version_id=ruleset_version_id,
                rule_version_ids=[str(rule_version.rule_version_id)],
                modified_by="test-maker",
            )
            await async_db_session.flush()

            # Step 5: Submit for approval
            await submit_ruleset_version(
                async_db_session, ruleset_version_id=ruleset_version_id, maker="test-maker"
            )
            await async_db_session.flush()

            # Step 6: Approve the RuleSetVersion (this triggers publishing)
            approved_version = await approve_ruleset_version(
                async_db_session, ruleset_version_id=ruleset_version_id, checker="test-checker"
            )
            await async_db_session.commit()

            # Verify ruleset version is APPROVED
            assert approved_version.status == EntityStatus.APPROVED.value

            # Verify manifest was created
            manifest_stmt = await async_db_session.execute(
                select(RuleSetManifest).where(
                    RuleSetManifest.ruleset_version_id == ruleset_version_id,
                )
            )
            manifests = manifest_stmt.scalars().all()
            assert len(manifests) == 1

            manifest = manifests[0]
            assert manifest.ruleset_version == 1
            assert manifest.created_by == "test-checker"
            assert manifest.checksum.startswith("sha256:")
            assert len(manifest.checksum) == 71  # "sha256:" + 64 hex chars
            assert manifest.artifact_uri.startswith("s3://")

            # Verify artifact exists in S3/MinIO
            # Extract key from URI
            import os

            s3_uri = manifest.artifact_uri
            bucket = os.environ.get("S3_BUCKET_NAME", "fraud-gov-artifacts")
            key = s3_uri.replace(f"s3://{bucket}/", "")

            response = s3_client.get_object(Bucket=bucket, Key=key)
            artifact_content = response["Body"].read().decode("utf-8")

            # Verify artifact is valid JSON
            artifact_json = json.loads(artifact_content)
            assert artifact_json["ruleType"] == "AUTH"
            assert artifact_json["version"] == ruleset_version.version
            assert artifact_json["rulesetId"] == str(ruleset_id)
            assert "rules" in artifact_json
            assert artifact_json["evaluation"]["mode"] == "FIRST_MATCH"

            # Verify checksum matches
            import hashlib

            computed_checksum = (
                f"sha256:{hashlib.sha256(artifact_content.encode('utf-8')).hexdigest()}"
            )
            assert computed_checksum == manifest.checksum

            # Verify runtime manifest.json was written
            publish_env = os.environ.get("APP_ENV", "local")
            manifest_key = f"rulesets/{publish_env}/IN/{ruleset_key}/manifest.json"
            manifest_response = s3_client.get_object(Bucket=bucket, Key=manifest_key)
            manifest_content = json.loads(manifest_response["Body"].read().decode("utf-8"))

            assert manifest_content["environment"] == publish_env
            assert manifest_content["country"] == "IN"
            assert manifest_content["region"] == "APAC"
            assert manifest_content["ruleset_key"] == ruleset_key
            assert manifest_content["ruleset_version"] == 1
            assert manifest_content["artifact_uri"] == manifest.artifact_uri
            assert manifest_content["checksum"] == manifest.checksum
            assert "published_at" in manifest_content

        finally:
            _cleanup_test_artifacts(s3_client, ruleset_key, "IN")

    @pytest.mark.anyio
    async def test_publish_MONITORING_ruleset_to_minio(
        self, async_db_session, s3_client, cleanup_manifests
    ):
        """Test MONITORING RuleSet publishing to MinIO."""
        settings = _get_settings()
        ruleset_key = "CARD_MONITORING"
        _cleanup_test_artifacts(s3_client, ruleset_key, "IN")

        try:
            # Create and approve a MONITORING RuleSet
            rule_id = uuid.uuid7()
            rule = Rule(
                rule_id=rule_id,
                rule_name="Test MONITORING Rule",
                rule_type=RuleType.MONITORING.value,
                current_version=1,
                status=EntityStatus.DRAFT.value,
                version=1,
                created_by="test-maker",
                created_at=datetime.now(UTC),
            )
            async_db_session.add(rule)
            await async_db_session.flush()

            rule_version = RuleVersion(
                rule_version_id=uuid.uuid7(),
                rule_id=rule_id,
                version=1,
                condition_tree={
                    "type": "CONDITION",
                    "field": "currency",
                    "operator": "EQ",
                    "value": "USD",
                },
                priority=50,
                created_by="test-maker",
                created_at=datetime.now(UTC),
                status=EntityStatus.APPROVED.value,
                approved_by="test-checker",
                approved_at=datetime.now(UTC),
            )
            async_db_session.add(rule_version)
            await async_db_session.flush()

            # Create RuleSet identity
            ruleset = await create_ruleset(
                async_db_session,
                environment=settings.publish_environment,
                region="APAC",
                country="IN",
                rule_type=RuleType.MONITORING.value,
                name="Test MONITORING RuleSet",
                description="For publisher e2e test",
                created_by="test-maker",
            )
            await async_db_session.flush()

            # Create RuleSetVersion
            ruleset_version = await create_ruleset_version(
                async_db_session,
                ruleset_id=ruleset.ruleset_id,
                created_by="test-maker",
            )
            await async_db_session.flush()

            await attach_rules_to_version(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_ids=[str(rule_version.rule_version_id)],
                modified_by="test-maker",
            )
            await async_db_session.flush()

            await submit_ruleset_version(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                maker="test-maker",
            )
            await async_db_session.flush()

            await approve_ruleset_version(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                checker="test-checker",
            )
            await async_db_session.commit()

            # Verify manifest for MONITORING
            manifest_result = await async_db_session.execute(
                select(RuleSetManifest).where(
                    RuleSetManifest.ruleset_version_id == ruleset_version.ruleset_version_id,
                )
            )
            manifest = manifest_result.scalar_one_or_none()
            assert manifest is not None
            assert manifest.ruleset_version == 1

            # Verify artifact in S3
            s3_uri = manifest.artifact_uri
            bucket = settings.s3_bucket_name
            key = s3_uri.replace(f"s3://{bucket}/", "")

            response = s3_client.get_object(Bucket=bucket, Key=key)
            artifact_content = response["Body"].read().decode("utf-8")
            artifact_json = json.loads(artifact_content)

            assert artifact_json["ruleType"] == "MONITORING"
            assert artifact_json["evaluation"]["mode"] == "ALL_MATCHING"

            # Verify runtime manifest.json
            manifest_key = f"rulesets/{settings.publish_environment}/IN/{ruleset_key}/manifest.json"
            manifest_response = s3_client.get_object(Bucket=bucket, Key=manifest_key)
            manifest_content = json.loads(manifest_response["Body"].read().decode("utf-8"))

            assert manifest_content["ruleset_key"] == ruleset_key
            assert manifest_content["ruleset_version"] == 1
            assert manifest_content["country"] == "IN"
            assert manifest_content["region"] == "APAC"

        finally:
            _cleanup_test_artifacts(s3_client, ruleset_key, "IN")

    @pytest.mark.anyio
    async def test_ALLOWLIST_ruleset_does_not_publish(
        self, async_db_session, s3_client, cleanup_manifests
    ):
        """Verify that ALLOWLIST RuleSets do NOT publish artifacts.

        ALLOWLIST and BLOCKLIST rule types don't map to runtime keys,
        so they should only be compiled locally, not published to S3.
        """
        settings = _get_settings()
        ruleset_key = "CARD_AUTH"  # For cleanup purposes
        _cleanup_test_artifacts(s3_client, ruleset_key, "IN")

        try:
            # Create a ALLOWLIST RuleSet
            rule_id = uuid.uuid7()
            rule = Rule(
                rule_id=rule_id,
                rule_name="Test ALLOWLIST Rule",
                rule_type=RuleType.ALLOWLIST.value,
                current_version=1,
                status=EntityStatus.DRAFT.value,
                version=1,
                created_by="test-maker",
                created_at=datetime.now(UTC),
            )
            async_db_session.add(rule)
            await async_db_session.flush()

            rule_version = RuleVersion(
                rule_version_id=uuid.uuid7(),
                rule_id=rule_id,
                version=1,
                condition_tree={
                    "type": "CONDITION",
                    "field": "amount",
                    "operator": "GT",
                    "value": 100,
                },
                priority=100,
                created_by="test-maker",
                created_at=datetime.now(UTC),
                status=EntityStatus.APPROVED.value,
                approved_by="test-checker",
                approved_at=datetime.now(UTC),
            )
            async_db_session.add(rule_version)
            await async_db_session.flush()

            # Create RuleSet identity
            ruleset = await create_ruleset(
                async_db_session,
                environment=settings.publish_environment,
                region="APAC",
                country="IN",
                rule_type=RuleType.ALLOWLIST.value,
                name="Test ALLOWLIST RuleSet",
                description="For publisher e2e test",
                created_by="test-maker",
            )
            await async_db_session.flush()

            # Create RuleSetVersion
            ruleset_version = await create_ruleset_version(
                async_db_session,
                ruleset_id=ruleset.ruleset_id,
                created_by="test-maker",
            )
            await async_db_session.flush()

            await attach_rules_to_version(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                rule_version_ids=[str(rule_version.rule_version_id)],
                modified_by="test-maker",
            )
            await async_db_session.flush()

            await submit_ruleset_version(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                maker="test-maker",
            )
            await async_db_session.flush()

            await approve_ruleset_version(
                async_db_session,
                ruleset_version_id=ruleset_version.ruleset_version_id,
                checker="test-checker",
            )
            await async_db_session.commit()

            # Verify NO manifest was created (ALLOWLIST doesn't map to runtime)
            manifest_result = await async_db_session.execute(
                select(RuleSetManifest).where(
                    RuleSetManifest.ruleset_version_id == ruleset_version.ruleset_version_id,
                )
            )
            manifest_count = len(manifest_result.scalars().all())
            assert manifest_count == 0

            # Verify ruleset version was still approved
            assert ruleset_version.status == EntityStatus.APPROVED.value

        finally:
            pass  # No artifacts to clean up

    @pytest.mark.anyio
    async def test_version_increments_on_subsequent_publish(
        self, async_db_session, s3_client, cleanup_manifests
    ):
        """Test that version numbers increment for each publish."""
        settings = _get_settings()
        ruleset_key = "CARD_AUTH"
        _cleanup_test_artifacts(s3_client, ruleset_key, "IN")

        try:
            # Helper to create a quick RuleVersion
            async def create_approved_rule():
                rule_id = uuid.uuid7()
                rule = Rule(
                    rule_id=rule_id,
                    rule_name="Quick Rule",
                    rule_type=RuleType.AUTH.value,
                    current_version=1,
                    status=EntityStatus.DRAFT.value,
                    version=1,
                    created_by="test-maker",
                    created_at=datetime.now(UTC),
                )
                async_db_session.add(rule)
                await async_db_session.flush()

                rv = RuleVersion(
                    rule_version_id=uuid.uuid7(),
                    rule_id=rule_id,
                    version=1,
                    condition_tree={
                        "type": "CONDITION",
                        "field": "amount",
                        "operator": "GT",
                        "value": 100,
                    },
                    priority=100,
                    created_by="test-maker",
                    created_at=datetime.now(UTC),
                    status=EntityStatus.APPROVED.value,
                    approved_by="test-checker",
                    approved_at=datetime.now(UTC),
                )
                async_db_session.add(rv)
                await async_db_session.flush()
                return rv

            # Create a single RuleSet identity (versioning happens at RuleSetVersion level)
            ruleset = await create_ruleset(
                async_db_session,
                environment=settings.publish_environment,
                region="APAC",
                country="IN",
                rule_type=RuleType.AUTH.value,
                name="Test RuleSet for Versioning",
                description="For versioning test",
                created_by="test-maker",
            )
            await async_db_session.flush()

            # Publish first RuleSetVersion (version 1)
            rv1 = await create_approved_rule()
            rsv1 = await create_ruleset_version(
                async_db_session,
                ruleset_id=ruleset.ruleset_id,
                created_by="test-maker",
            )
            await async_db_session.flush()
            await attach_rules_to_version(
                async_db_session,
                ruleset_version_id=rsv1.ruleset_version_id,
                rule_version_ids=[str(rv1.rule_version_id)],
                modified_by="test-maker",
            )
            await submit_ruleset_version(
                async_db_session, ruleset_version_id=rsv1.ruleset_version_id, maker="test-maker"
            )
            await async_db_session.flush()
            await approve_ruleset_version(
                async_db_session, ruleset_version_id=rsv1.ruleset_version_id, checker="test-checker"
            )
            await async_db_session.commit()

            # Verify version 1
            m1_result = await async_db_session.execute(
                select(RuleSetManifest).where(
                    RuleSetManifest.ruleset_version_id == rsv1.ruleset_version_id,
                )
            )
            m1 = m1_result.scalar_one_or_none()
            assert m1 is not None
            assert m1.ruleset_version == 1

            # Verify artifact key uses v1
            assert "v1/ruleset.json" in m1.artifact_uri

            # Publish second RuleSetVersion (should be version 2)
            rv2 = await create_approved_rule()
            rsv2 = await create_ruleset_version(
                async_db_session,
                ruleset_id=ruleset.ruleset_id,
                created_by="test-maker",
            )
            await async_db_session.flush()
            await attach_rules_to_version(
                async_db_session,
                ruleset_version_id=rsv2.ruleset_version_id,
                rule_version_ids=[str(rv2.rule_version_id)],
                modified_by="test-maker",
            )
            await submit_ruleset_version(
                async_db_session, ruleset_version_id=rsv2.ruleset_version_id, maker="test-maker"
            )
            await async_db_session.flush()
            await approve_ruleset_version(
                async_db_session, ruleset_version_id=rsv2.ruleset_version_id, checker="test-checker"
            )
            await async_db_session.commit()

            # Verify version 2
            m2_result = await async_db_session.execute(
                select(RuleSetManifest).where(
                    RuleSetManifest.ruleset_version_id == rsv2.ruleset_version_id,
                )
            )
            m2 = m2_result.scalar_one_or_none()
            assert m2 is not None
            assert m2.ruleset_version == 2

            # Verify artifact key uses v2
            assert "v2/ruleset.json" in m2.artifact_uri

            # Verify we have 2 manifests total
            # Note: Query by rule_type since ruleset_key is not stored in DB
            count_result = await async_db_session.execute(
                select(RuleSetManifest).where(
                    RuleSetManifest.rule_type == RuleType.AUTH.value,
                    RuleSetManifest.environment == settings.publish_environment,
                )
            )
            count = len(count_result.scalars().all())
            assert count == 2

            # Verify runtime manifest.json was updated to v2
            bucket = settings.s3_bucket_name
            manifest_key = f"rulesets/{settings.publish_environment}/IN/{ruleset_key}/manifest.json"
            manifest_response = s3_client.get_object(Bucket=bucket, Key=manifest_key)
            manifest_content = json.loads(manifest_response["Body"].read().decode("utf-8"))

            assert manifest_content["ruleset_version"] == 2
            assert manifest_content["artifact_uri"] == m2.artifact_uri
            assert manifest_content["country"] == "IN"
            assert manifest_content["region"] == "APAC"

        finally:
            _cleanup_test_artifacts(s3_client, ruleset_key, "IN")


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
async def cleanup_manifests(async_db_session):
    """Clean up test manifests after each test."""
    yield
    # Get fresh settings for cleanup
    settings = _get_settings()
    # Delete all test manifests
    await async_db_session.execute(
        select(RuleSetManifest).where(RuleSetManifest.environment == settings.publish_environment)
    )
    # For delete, we need to use a different approach
    from sqlalchemy import delete

    await async_db_session.execute(
        delete(RuleSetManifest).where(RuleSetManifest.environment == settings.publish_environment)
    )
    await async_db_session.commit()
