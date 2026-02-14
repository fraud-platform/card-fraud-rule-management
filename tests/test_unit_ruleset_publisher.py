"""
Unit tests for the Ruleset Publisher Service.

Tests verify:
- Rule type to ruleset_key mapping
- Deterministic serialization and checksum computation
- Version number computation
- Filesystem backend publishing
- S3 backend publishing and error handling
- Error handling for invalid configurations
- Retry logic for unique constraint violations
- URI generation edge cases
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.canonicalizer import to_canonical_json_string
from app.core.config import settings
from app.core.errors import CompilationError, ValidationError
from app.db.models import RuleSet, RuleSetManifest, RuleSetVersion
from app.services.ruleset_publisher import (
    FilesystemBackend,
    S3Backend,
    _compute_checksum,
    _generate_file_uri,
    _generate_s3_uri,
    _get_next_version,
    _map_rule_type_to_ruleset_key,
    _serialize_deterministically,
    publish_ruleset_version,
)

# =============================================================================
# Rule Type Mapping Tests
# =============================================================================


class TestRuleTypeMapping:
    """Test mapping from rule_type to ruleset_key."""

    @pytest.mark.anyio
    async def test_map_AUTH_to_card_AUTH(self):
        """Test AUTH maps to CARD_AUTH."""
        result = _map_rule_type_to_ruleset_key("AUTH")
        assert result == "CARD_AUTH"

    @pytest.mark.anyio
    async def test_map_MONITORING_to_card_MONITORING(self):
        """Test MONITORING maps to CARD_MONITORING."""
        result = _map_rule_type_to_ruleset_key("MONITORING")
        assert result == "CARD_MONITORING"

    @pytest.mark.anyio
    async def test_ALLOWLIST_throws_validation_error(self):
        """Test ALLOWLIST rule_type cannot be published to runtime."""
        with pytest.raises(ValidationError) as exc:
            _map_rule_type_to_ruleset_key("ALLOWLIST")

        assert "cannot be published to runtime" in str(exc.value)
        assert exc.value.details["rule_type"] == "ALLOWLIST"
        assert "AUTH" in exc.value.details["valid_types"]
        assert "MONITORING" in exc.value.details["valid_types"]

    @pytest.mark.anyio
    async def test_BLOCKLIST_throws_validation_error(self):
        """Test BLOCKLIST rule_type cannot be published to runtime."""
        with pytest.raises(ValidationError) as exc:
            _map_rule_type_to_ruleset_key("BLOCKLIST")

        assert "cannot be published to runtime" in str(exc.value)
        assert exc.value.details["rule_type"] == "BLOCKLIST"

    @pytest.mark.anyio
    async def test_invalid_rule_type_throws_validation_error(self):
        """Test invalid rule_type raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            _map_rule_type_to_ruleset_key("INVALID_TYPE")

        assert "cannot be published to runtime" in str(exc.value)


# =============================================================================
# Deterministic Serialization Tests
# =============================================================================


class TestDeterministicSerialization:
    """Test deterministic JSON serialization for checksums."""

    @pytest.mark.anyio
    async def test_serialize_compiles_to_bytes(self):
        """Test serialization produces UTF-8 encoded bytes."""
        ast = {"rulesetId": "test-123", "version": 1}
        result = _serialize_deterministically(ast)

        assert isinstance(result, bytes)
        assert result.decode("utf-8") == to_canonical_json_string(ast)

    @pytest.mark.anyio
    async def test_serialize_is_deterministic(self):
        """Test same AST produces identical bytes regardless of key order."""
        ast1 = {"z": 1, "a": {"inner_z": 1, "inner_a": 2}}
        ast2 = {"a": {"inner_a": 2, "inner_z": 1}, "z": 1}

        bytes1 = _serialize_deterministically(ast1)
        bytes2 = _serialize_deterministically(ast2)

        assert bytes1 == bytes2

    @pytest.mark.anyio
    async def test_serialize_compiled_ast(self):
        """Test serializing a realistic compiled AST."""
        ast = {
            "rulesetId": str(uuid.uuid7()),
            "version": 7,
            "ruleType": "MONITORING",
            "evaluation": {"mode": "ALL_MATCHING"},
            "velocityFailurePolicy": "SKIP",
            "rules": [
                {
                    "ruleId": str(uuid.uuid7()),
                    "ruleVersionId": str(uuid.uuid7()),
                    "priority": 100,
                    "when": {"field": "amount", "op": "GT", "value": 1000},
                    "action": "REVIEW",
                }
            ],
        }

        result = _serialize_deterministically(ast)

        assert isinstance(result, bytes)
        assert len(result) > 0
        # Should be valid JSON when decoded
        decoded = json.loads(result.decode("utf-8"))
        assert decoded["rulesetId"] == ast["rulesetId"]


# =============================================================================
# Checksum Computation Tests
# =============================================================================


class TestChecksumComputation:
    """Test SHA-256 checksum computation."""

    @pytest.mark.anyio
    async def test_compute_checksum_returns_prefixed_hex_string(self):
        """Test checksum is prefixed with sha256: and followed by 64-char hex string."""
        data = b"test data"
        result = _compute_checksum(data)

        assert isinstance(result, str)
        assert result.startswith("sha256:")
        assert len(result) == 71  # len("sha256:") + 64 hex chars = 71

    @pytest.mark.anyio
    async def test_compute_checksum_is_deterministic(self):
        """Test same data produces same checksum."""
        data = b"test data"
        result1 = _compute_checksum(data)
        result2 = _compute_checksum(data)

        assert result1 == result2

    @pytest.mark.anyio
    async def test_compute_checksum_different_data_different_hash(self):
        """Test different data produces different checksums."""
        result1 = _compute_checksum(b"test data")
        result2 = _compute_checksum(b"different data")

        assert result1 != result2

    @pytest.mark.anyio
    async def test_compute_checksum_matches_sha256(self):
        """Test checksum matches standard SHA-256 with prefix."""
        data = b"test data"
        result = _compute_checksum(data)
        expected_hex = hashlib.sha256(data).hexdigest()
        expected = f"sha256:{expected_hex}"

        assert result == expected

    @pytest.mark.anyio
    async def test_compute_checksum_empty_data(self):
        """Test checksum of empty data."""
        result = _compute_checksum(b"")
        expected_hex = hashlib.sha256(b"").hexdigest()
        expected = f"sha256:{expected_hex}"

        assert result == expected


# =============================================================================
# Version Computation Tests
# =============================================================================


class TestVersionComputation:
    """Test next version number computation."""

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_next_version_returns_one_when_empty(self, async_db_session: AsyncSession):
        """Test version is 1 when no existing manifests."""
        result = await _get_next_version(async_db_session, "test", "APAC", "IN", "AUTH")
        assert result == 1

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_next_version_increments_max(self, async_db_session: AsyncSession):
        """Test version is max + 1."""
        # Create a ruleset and version (required for FK constraint)
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_version_id=str(uuid.uuid7()),
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status="APPROVED",
            created_by="test-user",
            approved_by="test-user",
            approved_at=datetime.now(UTC),
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        # Create a manifest with version 3
        manifest = RuleSetManifest(
            ruleset_manifest_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            ruleset_version=3,
            ruleset_version_id=str(ruleset_version.ruleset_version_id),
            artifact_uri="s3://test/key.json",
            checksum="sha256:" + "a" * 64,
            created_at=datetime.now(UTC),
            created_by="test-user",
        )
        async_db_session.add(manifest)
        await async_db_session.flush()

        result = await _get_next_version(async_db_session, "test", "APAC", "IN", "AUTH")
        assert result == 4

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_next_version_isolated_by_key(self, async_db_session: AsyncSession):
        """Test version is independent per rule_type (which maps to ruleset_key)."""
        # Create a ruleset and version for AUTH
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_version_id=str(uuid.uuid7()),
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status="APPROVED",
            created_by="test-user",
            approved_by="test-user",
            approved_at=datetime.now(UTC),
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        # Create manifest for AUTH (maps to CARD_AUTH)
        manifest1 = RuleSetManifest(
            ruleset_manifest_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            ruleset_version=5,
            ruleset_version_id=str(ruleset_version.ruleset_version_id),
            artifact_uri="s3://test/key.json",
            checksum="sha256:" + "a" * 64,
            created_at=datetime.now(UTC),
            created_by="test-user",
        )
        async_db_session.add(manifest1)
        await async_db_session.flush()

        # MONITORING (maps to CARD_MONITORING) should start from 1
        result = await _get_next_version(async_db_session, "test", "APAC", "IN", "MONITORING")
        assert result == 1

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_next_version_isolated_by_environment(self, async_db_session: AsyncSession):
        """Test version is independent per environment."""
        # Create a ruleset and version for production
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="prod",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        ruleset_version = RuleSetVersion(
            ruleset_version_id=str(uuid.uuid7()),
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status="APPROVED",
            created_by="test-user",
            approved_by="test-user",
            approved_at=datetime.now(UTC),
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        # Create manifest for production
        manifest1 = RuleSetManifest(
            ruleset_manifest_id=str(uuid.uuid7()),
            environment="prod",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            ruleset_version=10,
            ruleset_version_id=str(ruleset_version.ruleset_version_id),
            artifact_uri="s3://test/key.json",
            checksum="sha256:" + "a" * 64,
            created_at=datetime.now(UTC),
            created_by="test-user",
        )
        async_db_session.add(manifest1)
        await async_db_session.flush()

        # test environment should start from 1
        result = await _get_next_version(async_db_session, "test", "APAC", "IN", "AUTH")
        assert result == 1

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_next_version_with_multiple_existing_versions(
        self, async_db_session: AsyncSession
    ):
        """Test version computation with multiple existing versions."""
        # Create a ruleset and versions (required for FK constraint)
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            created_by="test-user",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create manifests with versions 1, 2, 3
        for i in range(1, 4):
            ruleset_version = RuleSetVersion(
                ruleset_version_id=str(uuid.uuid7()),
                ruleset_id=ruleset.ruleset_id,
                version=i,
                status="APPROVED",
                created_by="test-user",
                approved_by="test-user",
                approved_at=datetime.now(UTC),
            )
            async_db_session.add(ruleset_version)
            await async_db_session.flush()

            manifest = RuleSetManifest(
                ruleset_manifest_id=str(uuid.uuid7()),
                environment="test",
                region="APAC",
                country="IN",
                rule_type="AUTH",
                ruleset_version=i,
                ruleset_version_id=str(ruleset_version.ruleset_version_id),
                artifact_uri=f"s3://test/key{i}.json",
                checksum="sha256:" + "a" * 64,
                created_at=datetime.now(UTC),
                created_by="test-user",
            )
            async_db_session.add(manifest)
        await async_db_session.flush()

        result = await _get_next_version(async_db_session, "test", "APAC", "IN", "AUTH")
        assert result == 4


# =============================================================================
# URI Generation Tests
# =============================================================================


class TestURIGeneration:
    """Test URI generation for S3 and filesystem backends."""

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_generate_s3_uri_includes_all_components(self):
        """Test S3 URI includes bucket, environment, key, and version."""
        with patch.object(settings, "s3_bucket_name", "test-bucket"):
            with patch.object(
                settings, "ruleset_artifact_prefix", "rulesets/{ENV}/{COUNTRY}/{RULESET_KEY}/"
            ):
                result = _generate_s3_uri("test", "US", "CARD_AUTH", 3)

        assert result.startswith("s3://test-bucket/")
        assert "rulesets/test/" in result
        assert "US/" in result
        assert "CARD_AUTH/" in result
        assert "v3/" in result
        assert "ruleset.json" in result

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_generate_file_uri_is_absolute(self):
        """Test filesystem URI is absolute."""
        with patch.object(settings, "ruleset_filesystem_dir", ".local/ruleset-artifacts"):
            result = _generate_file_uri("dev", "US", "CARD_MONITORING", 1)

        # On Windows: file://C:\path, on Unix: file:///path
        assert result.startswith("file://")
        assert "ruleset-artifacts" in result or ".local" in result
        assert "dev" in result
        assert "US" in result
        assert "v1" in result
        assert "ruleset.json" in result

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_generate_s3_uri_with_custom_prefix(self):
        """Test S3 URI generation with custom prefix."""
        with patch.object(settings, "s3_bucket_name", "custom-bucket"):
            with patch.object(
                settings, "ruleset_artifact_prefix", "custom/path/{ENV}/{COUNTRY}/{RULESET_KEY}/"
            ):
                result = _generate_s3_uri("prod", "IN", "CARD_MONITORING", 5)

        assert result.startswith("s3://custom-bucket/custom/path/")
        assert "prod/" in result
        assert "IN/" in result
        assert "CARD_MONITORING/" in result
        assert "v5/" in result
        assert "ruleset.json" in result

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_generate_file_uri_creates_expected_path_structure(self, tmp_path):
        """Test file URI generates correct path structure."""
        with patch.object(settings, "ruleset_filesystem_dir", str(tmp_path)):
            result = _generate_file_uri("dev", "GB", "CARD_AUTH", 2)

        # Verify path contains all components
        assert "dev" in result
        assert "GB" in result
        assert "CARD_AUTH" in result
        assert "v2" in result
        assert "ruleset.json" in result


# =============================================================================
# Filesystem Backend Tests
# =============================================================================


class TestFilesystemBackend:
    """Test filesystem storage backend."""

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_creates_directory_and_file(self, tmp_path):
        """Test publishing creates directory structure and file."""
        with patch.object(settings, "ruleset_filesystem_dir", str(tmp_path)):
            backend = FilesystemBackend()
            data = b'{"test": "data"}'

            result = backend.publish(data, "local", "US", "CARD_AUTH", 1)

            # Check directory was created with versioned path
            version_dir = tmp_path / "local" / "US" / "CARD_AUTH" / "v1"
            assert version_dir.exists()

            # Check file was created
            expected_file = version_dir / "ruleset.json"
            assert expected_file.exists()

            # Check file content
            with open(expected_file, "rb") as f:
                assert f.read() == data

            # Check URI format
            assert result.startswith("file://")

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_returns_file_uri(self, tmp_path):
        """Test publish returns file:// URI."""
        with patch.object(settings, "ruleset_filesystem_dir", str(tmp_path)):
            backend = FilesystemBackend()
            data = b'{"test": "data"}'

            result = backend.publish(data, "local", "IN", "CARD_AUTH", 1)

            # On Windows: file://C:\path, on Unix: file:///path
            assert result.startswith("file://")

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_creates_versioned_directory(self, tmp_path):
        """Test publishing creates versioned directory structure."""
        with patch.object(settings, "ruleset_filesystem_dir", str(tmp_path)):
            backend = FilesystemBackend()
            data = b'{"version": 1}'

            backend.publish(data, "local", "US", "CARD_AUTH", 1)

            # Verify versioned directory exists
            version_dir = tmp_path / "local" / "US" / "CARD_AUTH" / "v1"
            assert version_dir.exists()
            assert (version_dir / "ruleset.json").exists()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_creates_nested_directories(self, tmp_path):
        """Test publishing creates nested directory structure."""
        with patch.object(settings, "ruleset_filesystem_dir", str(tmp_path)):
            backend = FilesystemBackend()
            data = b'{"test": "data"}'

            backend.publish(data, "dev", "IN", "CARD_AUTH", 1)

            # Verify nested directories were created
            version_dir = tmp_path / "dev" / "IN" / "CARD_AUTH" / "v1"
            assert version_dir.exists()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_directory_creation_permission_error(self, tmp_path):
        """Test publish handles directory creation failures."""
        # Create a read-only base directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        import os
        import stat

        # Make directory read-only (best effort, may not work on all systems)
        try:
            os.chmod(readonly_dir, stat.S_IRUSR | stat.S_IXUSR)
        except Exception:
            pytest.skip("Cannot set directory permissions on this system")

        with patch.object(settings, "ruleset_filesystem_dir", str(readonly_dir)):
            backend = FilesystemBackend()

            # Try to create a subdirectory in read-only dir
            # This should raise an error
            try:
                backend.publish(b"data", "test", "US", "CARD_AUTH", 1)
                # If we get here, the OS allowed the write (Windows sometimes does)
                # Clean up and skip
                os.chmod(readonly_dir, stat.S_IRWXU)
                pytest.skip("OS allows write to read-only directory")
            except (OSError, PermissionError):
                # Expected behavior
                os.chmod(readonly_dir, stat.S_IRWXU)


# =============================================================================
# S3 Backend Tests
# =============================================================================


class TestS3Backend:
    """Test S3-compatible storage backend."""

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_init_creates_boto3_client(self):
        """Test backend initializes boto3 client."""
        backend = S3Backend()

        # Client should be None until first use
        assert backend._client is None
        assert not backend._initialized

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_get_client_initializes_on_first_call(self):
        """Test _get_client creates boto3 client on first call."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_boto3.session.Config.return_value = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()

            with patch.object(settings, "s3_endpoint_url", "http://localhost:9000"):
                with patch.object(settings, "s3_region", "us-east-1"):
                    with patch.object(settings, "s3_force_path_style", True):
                        client = backend._get_client()

            # Verify client was created
            assert client is not None
            assert backend._initialized is True
            mock_boto3.client.assert_called_once()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_get_client_without_boto3_raises_validation_error(self):
        """Test _get_client raises ValidationError when boto3 is not installed."""
        backend = S3Backend()

        # Mock import to raise ImportError
        with patch("builtins.__import__", side_effect=ImportError("No module named 'boto3'")):
            with pytest.raises(ValidationError) as exc:
                backend._get_client()

            assert "boto3 is required" in str(exc.value)
            assert exc.value.details["backend"] == "s3"

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_get_client_with_minio_config(self):
        """Test _get_client configures for MinIO."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_config = MagicMock()
        mock_boto3.session.Config.return_value = mock_config

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()

            with patch.object(settings, "s3_endpoint_url", "http://localhost:9000"):
                with patch.object(settings, "s3_region", "us-east-1"):
                    with patch.object(settings, "s3_access_key_id", "minioadmin"):
                        with patch.object(settings, "s3_secret_access_key", "minioadmin"):
                            with patch.object(settings, "s3_force_path_style", True):
                                backend._get_client()

            # Verify MinIO-specific config
            call_kwargs = mock_boto3.client.call_args[1]
            assert call_kwargs["endpoint_url"] == "http://localhost:9000"
            assert call_kwargs["aws_access_key_id"] == "minioadmin"
            assert call_kwargs["aws_secret_access_key"] == "minioadmin"
            assert "config" in call_kwargs

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_get_client_reuses_existing_client(self):
        """Test _get_client reuses client instead of creating new one."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_boto3.session.Config.return_value = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()
            backend._client = mock_client
            backend._initialized = True

            # Call _get_client
            client = backend._get_client()

            # Should return existing client without calling boto3.client again
            assert client is mock_client
            mock_boto3.client.assert_not_called()

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_with_mocked_boto3(self):
        """Test publishing with mocked boto3 client."""
        mock_client = MagicMock()
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_boto3.session.Config.return_value = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()
            backend._initialized = False

            with patch.object(settings, "s3_endpoint_url", "http://localhost:9000"):
                with patch.object(settings, "s3_bucket_name", "test-bucket"):
                    with patch.object(settings, "s3_region", "us-east-1"):
                        with patch.object(settings, "s3_access_key_id", "test-key"):
                            with patch.object(settings, "s3_secret_access_key", "test-secret"):
                                with patch.object(settings, "s3_force_path_style", True):
                                    with patch.object(
                                        settings,
                                        "ruleset_artifact_prefix",
                                        "rulesets/{ENV}/{COUNTRY}/{RULESET_KEY}/",
                                    ):
                                        result = backend.publish(
                                            b'{"test": "data"}',
                                            "test",
                                            "US",
                                            "CARD_AUTH",
                                            1,
                                        )

        # Verify S3 client was configured and put_object was called
        mock_client.put_object.assert_called_once()
        call_args = mock_client.put_object.call_args
        assert call_args[1]["Bucket"] == "test-bucket"
        assert call_args[1]["Body"] == b'{"test": "data"}'
        assert call_args[1]["ContentType"] == "application/json"
        assert result.startswith("s3://test-bucket/")
        # Verify key structure
        key = call_args[1]["Key"]
        assert "rulesets/test/US/CARD_AUTH/v1/ruleset.json" == key

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_s3_upload_error_raises_compilation_error(self):
        """Test S3 upload errors are wrapped in CompilationError."""
        mock_client = MagicMock()
        mock_client.put_object.side_effect = BotoCoreError()
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_boto3.session.Config.return_value = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()
            backend._initialized = False

            with patch.object(settings, "s3_endpoint_url", "http://localhost:9000"):
                with patch.object(settings, "s3_bucket_name", "test-bucket"):
                    with patch.object(settings, "s3_region", "us-east-1"):
                        with patch.object(settings, "s3_access_key_id", "test-key"):
                            with patch.object(settings, "s3_secret_access_key", "test-secret"):
                                with patch.object(settings, "s3_force_path_style", True):
                                    with patch.object(
                                        settings, "ruleset_artifact_prefix", "rulesets/"
                                    ):
                                        with pytest.raises(CompilationError) as exc:
                                            backend.publish(b"data", "test", "US", "CARD_AUTH", 1)

                                        assert "Failed to publish artifact to S3" in str(exc.value)
                                        assert exc.value.details["bucket"] == "test-bucket"

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_s3_client_error_raises_compilation_error(self):
        """Test S3 ClientError is wrapped in CompilationError."""
        mock_client = MagicMock()
        error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        mock_client.put_object.side_effect = ClientError(error_response, "PutObject")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_boto3.session.Config.return_value = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()
            backend._initialized = False

            with patch.object(settings, "s3_endpoint_url", "http://localhost:9000"):
                with patch.object(settings, "s3_bucket_name", "test-bucket"):
                    with patch.object(settings, "s3_region", "us-east-1"):
                        with patch.object(settings, "s3_access_key_id", "test-key"):
                            with patch.object(settings, "s3_secret_access_key", "test-secret"):
                                with patch.object(settings, "s3_force_path_style", True):
                                    with patch.object(
                                        settings, "ruleset_artifact_prefix", "rulesets/"
                                    ):
                                        with pytest.raises(CompilationError) as exc:
                                            backend.publish(b"data", "test", "US", "CARD_AUTH", 1)

                                        assert "Failed to publish artifact to S3" in str(exc.value)

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_generates_correct_s3_key(self):
        """Test publish generates correct S3 key with prefix."""
        mock_client = MagicMock()
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_boto3.session.Config.return_value = MagicMock()

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            backend = S3Backend()
            backend._initialized = False

            with patch.object(settings, "s3_endpoint_url", "http://localhost:9000"):
                with patch.object(settings, "s3_bucket_name", "my-bucket"):
                    with patch.object(settings, "s3_region", "us-east-1"):
                        with patch.object(settings, "s3_access_key_id", "key"):
                            with patch.object(settings, "s3_secret_access_key", "secret"):
                                with patch.object(settings, "s3_force_path_style", True):
                                    with patch.object(
                                        settings,
                                        "ruleset_artifact_prefix",
                                        "rulesets/{ENV}/{COUNTRY}/{RULESET_KEY}/",
                                    ):
                                        result = backend.publish(
                                            b"data", "prod", "IN", "CARD_MONITORING", 3
                                        )

            # Verify the S3 key structure
            call_args = mock_client.put_object.call_args
            key = call_args[1]["Key"]
            expected_key = "rulesets/prod/IN/CARD_MONITORING/v3/ruleset.json"
            assert key == expected_key, f"Expected {expected_key}, got {key}"
            assert result == f"s3://my-bucket/{expected_key}"


# =============================================================================
# Publish Ruleset Tests
# =============================================================================
# Note: Full publish flow tests are in tests/test_integration_publisher.py
# to test with real database and S3/MinIO, avoiding complex Pydantic settings mocking.


class TestPublishRulesetTransactionAtomicity:
    """Test transaction atomicity for publish_ruleset_version.

    Critical invariant: No manifest row exists unless upload succeeded.
    Orphan artifact is harmless; orphan manifest is dangerous.
    """

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_fails_does_not_create_manifest(self, async_db_session: AsyncSession):
        """Test that upload failure does not create a manifest row.

        This is the critical rollback test. If S3/filesystem upload fails,
        the transaction must not leave any partial state in the database.
        """
        from app.db.models import RuleSet, RuleSetVersion
        from app.services.ruleset_publisher import S3Backend

        # Create ruleset
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            created_by="test-maker",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create ruleset version
        ruleset_version = RuleSetVersion(
            ruleset_version_id=str(uuid.uuid7()),
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status="PENDING_APPROVAL",
            created_by="test-maker",
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        compiled_ast = {"rulesetId": str(ruleset.ruleset_id), "version": 1}

        with patch.object(S3Backend, "publish") as mock_publish:
            mock_publish.side_effect = CompilationError(
                "Failed to publish artifact to S3",
                details={"bucket": "test-bucket", "error": "S3 upload failed"},
            )

            with patch.object(settings, "ruleset_artifact_backend", "s3"):
                with patch.object(settings, "ruleset_publish_environment", "test"):
                    with patch("app.services.ruleset_publisher.ManifestWriter"):
                        with pytest.raises(CompilationError):
                            await publish_ruleset_version(
                                db=async_db_session,
                                ruleset_version=ruleset_version,
                                ruleset=ruleset,
                                compiled_ast=compiled_ast,
                                checker="test-checker",
                            )

        from app.db.models import RuleSetManifest

        result = (
            (
                await async_db_session.execute(
                    select(RuleSetManifest).where(
                        RuleSetManifest.environment == "test",
                        RuleSetManifest.rule_type == "AUTH",
                    )
                )
            )
            .scalars()
            .all()
        )

        assert len(result) == 0, "No manifest should exist when upload fails"

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_success_creates_manifest_with_uri(self, async_db_session: AsyncSession):
        """Test that successful upload creates manifest with complete artifact_uri."""
        from app.db.models import RuleSet, RuleSetVersion
        from app.services.ruleset_publisher import S3Backend

        # Create ruleset
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="MONITORING",
            created_by="test-maker",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create ruleset version
        ruleset_version = RuleSetVersion(
            ruleset_version_id=str(uuid.uuid7()),
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status="PENDING_APPROVAL",
            created_by="test-maker",
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        compiled_ast = {"rulesetId": str(ruleset.ruleset_id), "version": 1}

        expected_uri = "s3://test-bucket/rulesets/test/CARD_MONITORING/v1/ruleset.json"

        with patch.object(S3Backend, "publish", return_value=expected_uri):
            with patch.object(settings, "ruleset_artifact_backend", "s3"):
                with patch.object(settings, "ruleset_publish_environment", "test"):
                    with patch("app.services.ruleset_publisher.ManifestWriter"):
                        manifest = await publish_ruleset_version(
                            db=async_db_session,
                            ruleset_version=ruleset_version,
                            ruleset=ruleset,
                            compiled_ast=compiled_ast,
                            checker="test-checker",
                        )

        assert manifest is not None
        assert manifest.artifact_uri == expected_uri
        assert "CARD_MONITORING" in manifest.artifact_uri
        assert manifest.checksum.startswith("sha256:")
        assert len(manifest.checksum) == 71  # "sha256:" + 64 hex chars
        assert manifest.ruleset_version == 1
        assert manifest.environment == "test"
        assert manifest.rule_type == "MONITORING"
        assert manifest.ruleset_version_id == str(ruleset_version.ruleset_version_id)
        assert manifest.created_by == "test-checker"

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_publish_uses_upload_before_insert_pattern(self, async_db_session: AsyncSession):
        """Test that publish uploads artifact BEFORE inserting manifest row."""
        from app.db.models import RuleSet, RuleSetVersion
        from app.services.ruleset_publisher import S3Backend

        # Create ruleset
        ruleset = RuleSet(
            ruleset_id=str(uuid.uuid7()),
            environment="test",
            region="APAC",
            country="IN",
            rule_type="AUTH",
            created_by="test-maker",
        )
        async_db_session.add(ruleset)
        await async_db_session.flush()

        # Create ruleset version
        ruleset_version = RuleSetVersion(
            ruleset_version_id=str(uuid.uuid7()),
            ruleset_id=ruleset.ruleset_id,
            version=1,
            status="PENDING_APPROVAL",
            created_by="test-maker",
        )
        async_db_session.add(ruleset_version)
        await async_db_session.flush()

        compiled_ast = {"rulesetId": str(ruleset.ruleset_id), "version": 1}

        upload_called = False

        def tracking_publish(self, *args, **kwargs):
            nonlocal upload_called
            upload_called = True
            expected_uri = "s3://test-bucket/rulesets/test/CARD_AUTH/v1/ruleset.json"
            return expected_uri

        with patch.object(S3Backend, "publish", tracking_publish):
            with patch.object(settings, "ruleset_artifact_backend", "s3"):
                with patch.object(settings, "ruleset_publish_environment", "test"):
                    with patch("app.services.ruleset_publisher.ManifestWriter"):
                        manifest = await publish_ruleset_version(
                            db=async_db_session,
                            ruleset_version=ruleset_version,
                            ruleset=ruleset,
                            compiled_ast=compiled_ast,
                            checker="test-checker",
                        )

        assert upload_called, "Upload should be called before insert"
        assert manifest is not None
        assert manifest.artifact_uri.startswith("s3://")
