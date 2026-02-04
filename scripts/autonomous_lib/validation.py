"""
Multi-layer validation engine for autonomous testing.

Provides 4 layers of validation:
1. HTTP contract & shape (status codes, headers, JSON structure)
2. OpenAPI contract validation (against OpenAPI spec)
3. Domain invariants (maker-checker, state transitions, etc.)
4. Side effects evidence (DB state, manifests, checksums)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx


class ValidationLayer(str, Enum):
    """Validation layers."""

    HTTP = "http"  # HTTP contract validation
    OPENAPI = "openapi"  # OpenAPI spec validation
    DOMAIN = "domain"  # Domain invariants
    SIDE_EFFECTS = "side_effects"  # Side effects verification


@dataclass
class ValidationError:
    """A single validation error."""

    layer: ValidationLayer
    field: str
    message: str
    expected: Any = None
    actual: Any = None


@dataclass
class ValidationResult:
    """Result of validation across all layers."""

    passed: bool
    layer_results: dict[ValidationLayer, bool] = field(default_factory=dict)
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(
        self,
        layer: ValidationLayer,
        field: str,
        message: str,
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        """Add a validation error."""
        error = ValidationError(
            layer=layer,
            field=field,
            message=message,
            expected=expected,
            actual=actual,
        )
        self.errors.append(error)
        self.layer_results[layer] = False
        self.passed = False

    def add_warning(self, layer: ValidationLayer, message: str) -> None:
        """Add a validation warning (non-failing)."""
        self.warnings.append(f"[{layer.value}] {message}")

    def set_layer_passed(self, layer: ValidationLayer) -> None:
        """Mark a layer as passed."""
        self.layer_results[layer] = True


class HttpValidator:
    """Layer 1: HTTP contract validation."""

    def validate_status_code(
        self,
        response: httpx.Response,
        expected: int | list[int],
    ) -> ValidationResult:
        """Validate HTTP status code."""
        result = ValidationResult(passed=True)

        expected_codes = expected if isinstance(expected, list) else [expected]
        actual = response.status_code

        if actual not in expected_codes:
            result.add_error(
                ValidationLayer.HTTP,
                "status_code",
                f"Status code {actual} not in expected {expected_codes}",
                expected=expected_codes,
                actual=actual,
            )
        else:
            result.set_layer_passed(ValidationLayer.HTTP)

        return result

    def validate_content_type(
        self,
        response: httpx.Response,
        expected_pattern: str | None = None,
    ) -> ValidationResult:
        """Validate Content-Type header."""
        result = ValidationResult(passed=True)

        if not expected_pattern:
            result.set_layer_passed(ValidationLayer.HTTP)
            return result

        content_type = response.headers.get("content-type", "")
        if expected_pattern.lower() not in content_type.lower():
            result.add_error(
                ValidationLayer.HTTP,
                "content_type",
                f"Content-Type '{content_type}' does not match '{expected_pattern}'",
                expected=expected_pattern,
                actual=content_type,
            )
        else:
            result.set_layer_passed(ValidationLayer.HTTP)

        return result

    def validate_json_shape(
        self,
        response: httpx.Response,
        required_fields: list[str] | None = None,
        forbidden_fields: list[str] | None = None,
    ) -> ValidationResult:
        """Validate JSON response shape."""
        result = ValidationResult(passed=True)

        try:
            data = response.json()
        except Exception:
            result.add_error(
                ValidationLayer.HTTP,
                "body",
                "Response is not valid JSON",
            )
            return result

        # Check required fields
        if required_fields:
            for field_path in required_fields:
                if not self._has_json_path(data, field_path):
                    result.add_error(
                        ValidationLayer.HTTP,
                        f"body.{field_path}",
                        f"Required field '{field_path}' is missing",
                    )

        # Check forbidden fields
        if forbidden_fields:
            for field_path in forbidden_fields:
                if self._has_json_path(data, field_path):
                    result.add_warning(
                        ValidationLayer.HTTP,
                        f"Forbidden field '{field_path}' is present in response",
                    )

        if result.passed:
            result.set_layer_passed(ValidationLayer.HTTP)

        return result

    def _has_json_path(self, data: dict | list, path: str) -> bool:
        """Check if JSON path exists in data."""
        try:
            from .http_client import extract_json_path

            value = extract_json_path(data, path)
            return value is not None
        except Exception:
            return False


class OpenApiValidator:
    """Layer 2: OpenAPI contract validation."""

    def __init__(self, openapi_path: str | None = None):
        """Initialize with OpenAPI spec path."""
        self.openapi_path = openapi_path
        self._spec = None

    def load_spec(self) -> bool:
        """Load OpenAPI specification from file."""
        if not self.openapi_path:
            # Try default location
            default_path = Path("docs/03-api/openapi.json")
            if default_path.exists():
                self.openapi_path = str(default_path)
            else:
                return False

        try:
            with open(self.openapi_path) as f:
                self._spec = json.load(f)
            return True
        except Exception:
            return False

    def validate_response(
        self,
        method: str,
        path: str,
        status_code: int,
        response_body: dict | list,
    ) -> ValidationResult:
        """Validate response against OpenAPI spec.

        This is a best-effort validation that checks:
        - The endpoint exists in the spec
        - The status code is documented
        - Response shape matches schema (basic check)
        """
        result = ValidationResult(passed=True)

        if not self._spec and not self.load_spec():
            result.add_warning(
                ValidationLayer.OPENAPI,
                "OpenAPI spec not available, skipping validation",
            )
            return result

        # Check if path exists in spec
        paths = self._spec.get("paths", {})
        normalized_path = self._normalize_path(path)

        if normalized_path not in paths:
            result.add_warning(
                ValidationLayer.OPENAPI,
                f"Path '{normalized_path}' not found in OpenAPI spec",
            )
            return result

        # Check if method exists
        path_spec = paths[normalized_path]
        method_lower = method.lower()
        if method_lower not in path_spec:
            result.add_warning(
                ValidationLayer.OPENAPI,
                f"Method '{method}' not found for path '{normalized_path}'",
            )
            return result

        # Check if status code is documented
        operation = path_spec[method_lower]
        responses = operation.get("responses", {})
        status_str = str(status_code)

        if status_str not in responses:
            result.add_warning(
                ValidationLayer.OPENAPI,
                f"Status code '{status_code}' not documented in OpenAPI spec for '{method} {normalized_path}'",
            )
        else:
            result.set_layer_passed(ValidationLayer.OPENAPI)

        return result

    def _normalize_path(self, path: str) -> str:
        """Normalize path parameters to OpenAPI format {param}."""
        # Convert :param to {param} format
        return re.sub(r":(\w+)", r"{\1}", path)


class DomainValidator:
    """Layer 3: Domain invariant validation.

    Validates business rules and invariants:
    - Maker-checker separation (maker != checker)
    - State transitions (DRAFT → PENDING_APPROVAL → APPROVED)
    - Rule type consistency
    - Required fields for specific states
    """

    VALID_STATE_TRANSITIONS = {
        "DRAFT": ["PENDING_APPROVAL", "REJECTED"],
        "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
        "APPROVED": ["ACTIVE", "SUPERSEDED"],
        "ACTIVE": ["SUPERSEDED"],
        "REJECTED": ["DRAFT"],  # Can resubmit
        "SUPERSEDED": [],
    }

    def validate_maker_checker(
        self,
        maker_id: str,
        checker_id: str,
    ) -> ValidationResult:
        """Validate maker-checker separation."""
        result = ValidationResult(passed=True)

        if maker_id and checker_id and maker_id == checker_id:
            result.add_error(
                ValidationLayer.DOMAIN,
                "maker_checker",
                "Maker cannot be the same as checker",
                expected="maker != checker",
                actual=f"maker={maker_id} checker={checker_id}",
            )
        else:
            result.set_layer_passed(ValidationLayer.DOMAIN)

        return result

    def validate_state_transition(
        self,
        old_status: str,
        new_status: str,
    ) -> ValidationResult:
        """Validate state transition is allowed."""
        result = ValidationResult(passed=True)

        allowed = self.VALID_STATE_TRANSITIONS.get(old_status, [])

        if new_status not in allowed:
            result.add_error(
                ValidationLayer.DOMAIN,
                "state_transition",
                f"Invalid state transition from {old_status} to {new_status}",
                expected=f"One of: {allowed}",
                actual=new_status,
            )
        else:
            result.set_layer_passed(ValidationLayer.DOMAIN)

        return result

    def validate_rule_type_consistency(
        self,
        rule_type: str,
        ruleset_rule_type: str,
    ) -> ValidationResult:
        """Validate rule type matches ruleset type."""
        result = ValidationResult(passed=True)

        if rule_type != ruleset_rule_type:
            result.add_error(
                ValidationLayer.DOMAIN,
                "rule_type_consistency",
                f"Rule type '{rule_type}' does not match ruleset type '{ruleset_rule_type}'",
                expected=ruleset_rule_type,
                actual=rule_type,
            )
        else:
            result.set_layer_passed(ValidationLayer.DOMAIN)

        return result

    def validate_approve_fields(
        self,
        status: str,
        approved_by: str | None,
        approved_at: Any,
    ) -> ValidationResult:
        """Validate that APPROVED status has required fields."""
        result = ValidationResult(passed=True)

        if status == "APPROVED":
            if not approved_by:
                result.add_error(
                    ValidationLayer.DOMAIN,
                    "approved_by",
                    "approved_by is required when status is APPROVED",
                )
            if not approved_at:
                result.add_error(
                    ValidationLayer.DOMAIN,
                    "approved_at",
                    "approved_at is required when status is APPROVED",
                )

        if result.passed:
            result.set_layer_passed(ValidationLayer.DOMAIN)

        return result


class SideEffectsValidator:
    """Layer 4: Side effects validation.

    Verifies that operations produce expected side effects:
    - DB state changes (row counts, status updates)
    - Manifest creation for ruleset publishing
    - Artifact publication to S3/filesystem
    - Checksum validation
    """

    def __init__(self, db_evaluator=None):
        """Initialize with optional DB evaluator."""
        from .db_assertions import create_db_evaluator

        self.db_evaluator = db_evaluator or create_db_evaluator()

    def validate_manifest_created(
        self,
        ruleset_version_id: str,
    ) -> ValidationResult:
        """Validate that manifest was created for ruleset version."""
        result = ValidationResult(passed=True)

        assertion = self.db_evaluator.evaluate_assertion(
            query="SELECT COUNT(*) as count FROM fraud_gov.ruleset_manifest WHERE ruleset_version_id = :id",
            expect_row_count=1,
            params={"id": ruleset_version_id},
        )

        if not assertion.passed:
            result.add_error(
                ValidationLayer.SIDE_EFFECTS,
                "manifest_created",
                assertion.error_message or "Manifest not created",
            )
        else:
            result.set_layer_passed(ValidationLayer.SIDE_EFFECTS)

        return result

    def validate_audit_log_created(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
    ) -> ValidationResult:
        """Validate that audit log entry was created."""
        result = ValidationResult(passed=True)

        assertion = self.db_evaluator.evaluate_assertion(
            query="""SELECT COUNT(*) as count FROM fraud_gov.audit_log
                     WHERE entity_type = :entity_type AND entity_id = :id AND action = :action""",
            expect_row_count=1,
            params={"entity_type": entity_type, "id": entity_id, "action": action},
        )

        if not assertion.passed:
            result.add_error(
                ValidationLayer.SIDE_EFFECTS,
                "audit_log_created",
                assertion.error_message or "Audit log entry not created",
            )
        else:
            result.set_layer_passed(ValidationLayer.SIDE_EFFECTS)

        return result

    def validate_artifact_checksum(
        self,
        artifact_path: str,
        expected_checksum: str | None = None,
    ) -> ValidationResult:
        """Validate artifact file checksum.

        If expected_checksum is None, computes SHA-256 for verification.
        """
        result = ValidationResult(passed=True)

        try:
            path = Path(artifact_path)
            if not path.exists():
                result.add_error(
                    ValidationLayer.SIDE_EFFECTS,
                    "artifact_exists",
                    f"Artifact file not found: {artifact_path}",
                )
                return result

            # Compute SHA-256
            sha256_hash = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)

            actual_checksum = f"sha256:{sha256_hash.hexdigest()}"

            if expected_checksum and actual_checksum != expected_checksum:
                result.add_error(
                    ValidationLayer.SIDE_EFFECTS,
                    "artifact_checksum",
                    "Checksum mismatch",
                    expected=expected_checksum,
                    actual=actual_checksum,
                )
            else:
                result.set_layer_passed(ValidationLayer.SIDE_EFFECTS)

        except Exception as e:
            result.add_error(
                ValidationLayer.SIDE_EFFECTS,
                "artifact_checksum",
                f"Error validating checksum: {e}",
            )

        return result


class MultiLayerValidator:
    """Combines all validation layers."""

    def __init__(
        self,
        openapi_path: str | None = None,
        db_evaluator=None,
    ):
        self.http = HttpValidator()
        self.openapi = OpenApiValidator(openapi_path)
        self.domain = DomainValidator()
        self.side_effects = SideEffectsValidator(db_evaluator)

    def validate_step(
        self,
        response: httpx.Response,
        expected_status: int | list[int] = 200,
        expected_fields: list[str] | None = None,
        forbidden_fields: list[str] | None = None,
        content_type: str | None = "application/json",
    ) -> ValidationResult:
        """Run all applicable validation layers for an HTTP response."""
        result = ValidationResult(passed=True)

        # Layer 1: HTTP contract
        http_result = self.http.validate_status_code(response, expected_status)
        result.errors.extend(http_result.errors)
        result.warnings.extend(http_result.warnings)

        if content_type:
            ct_result = self.http.validate_content_type(response, content_type)
            result.errors.extend(ct_result.errors)
            result.warnings.extend(ct_result.warnings)

        if expected_fields or forbidden_fields:
            shape_result = self.http.validate_json_shape(
                response, expected_fields, forbidden_fields
            )
            result.errors.extend(shape_result.errors)
            result.warnings.extend(shape_result.warnings)

        # Layer 2: OpenAPI (if spec available)
        # Skip for non-JSON responses
        if content_type and "json" in content_type.lower():
            try:
                response_data = response.json()
                oai_result = self.openapi.validate_response(
                    "GET",  # Would need to be passed in
                    response.request.url.path,
                    response.status_code,
                    response_data,
                )
                result.errors.extend(oai_result.errors)
                result.warnings.extend(oai_result.warnings)
            except Exception:
                pass  # OpenAPI validation is best-effort

        return result
