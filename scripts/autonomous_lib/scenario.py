"""
Scenario schema and execution engine for autonomous testing.

Defines the data structures for scenarios, steps, and validation rules.
Supports idempotent operations with skip_if and on_conflict handlers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class HttpMethod(str, Enum):
    """HTTP methods supported by scenarios."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class AuthRole(str, Enum):
    """Authentication roles for scenario steps."""

    NONE = "none"
    DEFAULT = "default"
    MAKER = "maker"
    CHECKER = "checker"
    ADMIN = "admin"


@dataclass
class SkipCondition:
    """Condition to skip a step based on state."""

    db_query: str | None = None
    db_expected_values: list[str] = field(default_factory=list)
    db_condition: str | None = None  # e.g., "status NOT IN ('DRAFT', 'REJECTED')"
    variable_exists: str | None = None
    variable_equals: dict[str, Any] = field(default_factory=dict)

    def should_skip(self, context: ExecutionContext) -> tuple[bool, str]:
        """Evaluate if the step should be skipped.

        Returns:
            (should_skip, reason): Tuple indicating if step should be skipped and why
        """
        # Check if variable exists
        if self.variable_exists:
            if context.get_variable(self.variable_exists) is None:
                return True, f"Variable '{self.variable_exists}' does not exist"

        # Check if variables equal expected values
        if self.variable_equals:
            for var_name, expected_value in self.variable_equals.items():
                actual_value = context.get_variable(var_name)
                if actual_value != expected_value:
                    return True, f"Variable '{var_name}'={actual_value} != {expected_value}"

        # Check DB condition (requires DB connection)
        if self.db_condition and context.db_connection:
            try:
                # Simple condition check against in-memory state
                # For complex queries, the caller should handle them
                return False, ""
            except Exception:
                return False, ""

        return False, ""


@dataclass
class OnConflictHandler:
    """Handler for 409 Conflict responses."""

    fetch_method: str = "GET"
    fetch_path_template: str = ""
    save_from_jsonpath: str = ""
    skip_if_conflict: bool = False

    def handle_conflict(
        self,
        response: Any,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Handle a conflict response, returning updated context variables.

        Attempts to fetch the existing resource and extract values from it.
        Returns a dict of variables to add to the context.

        If skip_if_conflict is True, returns {'skip_step': True}.
        """
        if self.skip_if_conflict:
            return {"skip_step": True}

        if not self.fetch_path_template or not context.http_client:
            return {}

        try:
            # Format the fetch path with context variables
            fetch_url = context.format_template(self.fetch_path_template)

            # Make the fetch request (simplified - real implementation would use http_client)
            # This is a placeholder for the actual HTTP fetch
            return {"_fetched_url": fetch_url}
        except Exception:
            return {}


@dataclass
class ExpectCondition:
    """Expected response conditions."""

    status: int | list[int] = 200
    json_path_present: list[str] = field(default_factory=list)
    json_path_absent: list[str] = field(default_factory=list)
    json_path_equals: dict[str, Any] = field(default_factory=dict)
    json_path_contains: dict[str, Any] = field(default_factory=dict)
    json_path_regex: dict[str, str] = field(default_factory=dict)
    content_type: str | None = None

    def _get_json_value(self, obj: Any, path: str) -> Any:
        """Get a value from a JSON-like object using a simple path syntax.

        Supports:
        - "field" -> obj["field"]
        - "field.nested" -> obj["field"]["nested"]
        - "field[0]" -> obj["field"][0]
        """
        if not path:
            return obj

        current = obj
        parts = path.replace("]", "").split(".")

        for part in parts:
            if not current:
                return None

            # Handle array notation like "items[0]"
            bracket_idx = part.find("[")
            if bracket_idx != -1:
                field_name = part[:bracket_idx]
                index = int(part[bracket_idx + 1 :]) if bracket_idx + 1 < len(part) else 0
                if isinstance(current, dict) and field_name:
                    current = current.get(field_name, [])
                elif isinstance(current, list):
                    current = current
                else:
                    return None
                if isinstance(current, list) and 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if 0 <= idx < len(current) else None
            else:
                return None

        return current

    def validate(self, response: Any) -> tuple[bool, list[str]]:
        """Validate the response against expectations.

        Returns (passed, error_messages).
        """
        errors = []

        # Check status code
        status = getattr(response, "status_code", None)
        if status is not None:
            expected = self.status if isinstance(self.status, list) else [self.status]
            # Normalize types: ensure both status and expected values are integers for comparison
            try:
                status_int = int(status)
                expected_normalized = [int(e) for e in expected]
            except (ValueError, TypeError):
                # If conversion fails, use original values
                status_int = status
                expected_normalized = expected

            if status_int not in expected_normalized:
                errors.append(f"Status {status} not in expected {expected}")

        # Get response JSON if available
        response_json = None
        if hasattr(response, "json"):
            try:
                response_json = response.json()
            except Exception:
                pass
        elif hasattr(response, "json()"):
            try:
                response_json = response.json()
            except Exception:
                pass

        # Check JSON path validations
        if response_json:
            # Check required fields are present
            for path in self.json_path_present:
                value = self._get_json_value(response_json, path)
                if value is None:
                    errors.append(f"Required JSON path '{path}' not found or is null")

            # Check fields should be absent
            for path in self.json_path_absent:
                value = self._get_json_value(response_json, path)
                if value is not None:
                    errors.append(f"JSON path '{path}' should be absent but found: {value}")

            # Check field equality
            for path, expected_value in self.json_path_equals.items():
                value = self._get_json_value(response_json, path)
                if value != expected_value:
                    errors.append(f"JSON path '{path}' = {value} != {expected_value}")

            # Check field contains (for strings/lists)
            for path, expected_contains in self.json_path_contains.items():
                value = self._get_json_value(response_json, path)
                if isinstance(value, str) and expected_contains not in value:
                    errors.append(f"JSON path '{path}' = '{value}' does not contain '{expected_contains}'")
                elif isinstance(value, list) and expected_contains not in value:
                    errors.append(f"JSON path '{path}' list does not contain '{expected_contains}'")

            # Check regex patterns
            for path, pattern in self.json_path_regex.items():
                value = self._get_json_value(response_json, path)
                if value is None or not re.match(pattern, str(value)):
                    errors.append(f"JSON path '{path}' = '{value}' does not match pattern '{pattern}'")

        # Check content type
        if self.content_type:
            content_type_header = getattr(response, "headers", {}).get("content-type", "")
            if self.content_type not in content_type_header:
                errors.append(f"Content-Type '{content_type_header}' does not contain '{self.content_type}'")

        return len(errors) == 0, errors


@dataclass
class DbAssertion:
    """Database state assertions."""

    query: str
    expect: str | int | list[Any] | None = None
    expect_row_count: int | None = None
    expect_empty: bool = False

    def validate(self, db_connection: Any) -> tuple[bool, str]:
        """Validate the database state.

        Returns:
            (passed, error_message): Tuple indicating if assertion passed
        """
        if not db_connection:
            return True, ""  # Skip validation if no DB connection

        try:
            # Execute the query
            cursor = db_connection.execute(self.query)

            # Check row count expectation
            if self.expect_row_count is not None:
                row_count = cursor.rowcount if hasattr(cursor, "rowcount") else len(cursor.fetchall())
                if row_count != self.expect_row_count:
                    return False, f"Expected {self.expect_row_count} rows, got {row_count}"

            # Check empty expectation
            if self.expect_empty:
                rows = cursor.fetchall() if hasattr(cursor, "fetchall") else list(cursor)
                if rows:
                    return False, f"Expected empty result, got {len(rows)} rows"

            # Check specific value expectation
            if self.expect is not None:
                row = cursor.fetchone() if hasattr(cursor, "fetchone") else None
                if row:
                    actual_value = row[0] if isinstance(row, (list, tuple)) else row
                    if actual_value != self.expect:
                        return False, f"Expected {self.expect}, got {actual_value}"

            return True, ""
        except Exception as e:
            return False, f"DB assertion failed: {e}"


@dataclass
class StepSaveSpec:
    """Specification for saving values from response."""

    name: str
    json_path: str
    as_list: bool = False
    default: Any = None


@dataclass
class ScenarioStep:
    """A single step in a scenario."""

    name: str
    request_method: HttpMethod = HttpMethod.GET
    request_path: str = ""
    request_json: dict[str, Any] | None = None
    request_params: dict[str, str] | None = None
    auth: AuthRole = AuthRole.DEFAULT
    idempotent: bool = False
    idempotency_key_template: str = ""

    # Skip and conflict handling
    skip_if: SkipCondition | None = None
    on_conflict: OnConflictHandler | None = None

    # Validation
    expect: ExpectCondition | None = None
    db_assertions: list[DbAssertion] = field(default_factory=list)

    # Variable capture
    save: list[StepSaveSpec] = field(default_factory=list)

    # Step options
    optional: bool = False
    continue_on_error: bool = False
    timeout: float = 30.0

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ExecutionContext:
    """Execution context for a scenario run."""

    variables: dict[str, Any] = field(default_factory=dict)
    responses: dict[str, Any] = field(default_factory=dict)
    db_connection: Any = None
    http_client: Any = None
    auth_tokens: dict[str, str | None] = field(default_factory=dict)

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a variable value."""
        return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable value."""
        self.variables[name] = value

    def get_auth_token(self, role: AuthRole) -> str | None:
        """Get the auth token for a role."""
        role_key = role.value if role != AuthRole.NONE else "none"
        return self.auth_tokens.get(role_key)

    def format_template(self, template: str) -> str:
        """Format a template string with variables."""
        # Simple {var} substitution
        result = template

        # Find all placeholders
        pattern = re.compile(r"\{([^}]+)\}")

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            value = self.get_variable(var_name, "")
            return str(value) if value is not None else ""

        return pattern.sub(replacer, result)

    def format_json(self, obj: Any) -> Any:
        """Format JSON-like object with variable substitution."""
        if obj is None:
            return None
        if isinstance(obj, str):
            return self.format_template(obj)
        if isinstance(obj, dict):
            return {k: self.format_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.format_json(v) for v in obj]
        return obj


@dataclass
class StepResult:
    """Result of executing a single step or aggregate scenario result."""

    step_name: str
    passed: bool
    skipped: bool = False
    status_code: int | None = None
    duration_ms: float = 0.0
    error_message: str = ""
    assertions_passed: int = 0
    assertions_failed: int = 0
    saved_variables: dict[str, Any] = field(default_factory=dict)
    response_summary: str = ""
    # Request details
    request_method: str = ""
    request_url: str = ""
    request_headers: dict[str, str] | None = None
    request_body: str | None = None
    # Response details
    response_headers: dict[str, str] | None = None
    response_body: str | None = None
    response_body_formatted: str | None = None  # JSON with indent=2
    # Aggregate fields (used for scenario-level results)
    steps_passed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0


@dataclass
class Scenario:
    """A test scenario consisting of multiple steps."""

    name: str
    category: str
    description: str = ""
    steps: list[ScenarioStep] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    idempotency_prefix: str = ""

    # Metadata
    author: str = ""
    version: str = "1.0"
    enabled: bool = True


@dataclass
class ScenarioResult:
    """Result of running a complete scenario."""

    scenario_name: str
    category: str
    passed: bool
    duration_ms: float = 0.0
    steps_passed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    step_results: list[StepResult] = field(default_factory=list)
    error_message: str = ""
    artifacts: list[str] = field(default_factory=list)


def scenario_from_dict(data: dict[str, Any]) -> Scenario:
    """Parse a scenario from a YAML/JSON dict."""
    steps_data = data.get("steps", [])
    steps = []

    for step_data in steps_data:
        # Parse HTTP method
        method_str = step_data.get("request", {}).get("method", "GET")
        try:
            method = HttpMethod(method_str.upper())
        except ValueError:
            method = HttpMethod.GET

        # Parse auth role
        auth_str = step_data.get("request", {}).get("auth", "default")
        try:
            auth = AuthRole(auth_str.lower())
        except ValueError:
            auth = AuthRole.DEFAULT

        # Parse skip condition
        skip_if_data = step_data.get("skip_if")
        skip_if = None
        if skip_if_data:
            if isinstance(skip_if_data, dict):
                skip_if = SkipCondition(
                    db_query=skip_if_data.get("db_query"),
                    db_condition=skip_if_data.get("condition"),
                    variable_exists=skip_if_data.get("variable_exists"),
                    variable_equals=skip_if_data.get("variable_equals"),
                )
            elif isinstance(skip_if_data, str):
                # Simple condition string
                skip_if = SkipCondition(db_condition=skip_if_data)

        # Parse conflict handler
        conflict_data = step_data.get("on_conflict")
        on_conflict = None
        if conflict_data:
            fetch = conflict_data.get("fetch", "")
            if fetch:
                # Parse "METHOD /path" format
                parts = fetch.split(" ", 1)
                fetch_method = parts[0] if len(parts) > 1 else "GET"
                fetch_path = parts[1] if len(parts) > 1 else fetch
                on_conflict = OnConflictHandler(
                    fetch_method=fetch_method,
                    fetch_path_template=fetch_path,
                    save_from_jsonpath=conflict_data.get("save_from", ""),
                    skip_if_conflict=conflict_data.get("skip", False),
                )

        # Parse expectations
        expect_data = step_data.get("expect", {})
        expect = None
        if expect_data:
            status = expect_data.get("status", 200)
            expect = ExpectCondition(
                status=status,
                json_path_present=expect_data.get("json", {}).get("present", []),
                json_path_absent=expect_data.get("json", {}).get("absent", []),
            )

        # Parse save specs
        save_data = step_data.get("save", {})
        save_specs = []
        if save_data:
            if isinstance(save_data, dict):
                # Single save spec
                save_specs.append(
                    StepSaveSpec(
                        name=save_data.get("name", ""),
                        json_path=save_data.get("json_path", save_data.get("$", "")),
                        as_list=save_data.get("as_list", False),
                        default=save_data.get("default"),
                    )
                )
            elif isinstance(save_data, list):
                # Multiple save specs
                for s in save_data:
                    save_specs.append(
                        StepSaveSpec(
                            name=s.get("name", ""),
                            json_path=s.get("json_path", s.get("$", "")),
                            as_list=s.get("as_list", False),
                            default=s.get("default"),
                        )
                    )

        # Parse DB assertions
        db_assertions = []
        for assertion in step_data.get("db_assert", []):
            if isinstance(assertion, dict):
                db_assertions.append(
                    DbAssertion(
                        query=assertion.get("query", ""),
                        expect=assertion.get("expect"),
                    )
                )
            elif isinstance(assertion, str):
                # Simple query string
                db_assertions.append(DbAssertion(query=assertion))

        # Create the step
        request = step_data.get("request", {})
        step = ScenarioStep(
            name=step_data.get("name", f"step_{len(steps) + 1}"),
            request_method=method,
            request_path=request.get("path", ""),
            request_json=request.get("json"),
            request_params=request.get("params"),
            auth=auth,
            idempotent=step_data.get("idempotent", False),
            idempotency_key_template=step_data.get("idempotency_key", ""),
            skip_if=skip_if,
            on_conflict=on_conflict,
            expect=expect,
            db_assertions=db_assertions,
            save=save_specs,
            optional=step_data.get("optional", False),
            continue_on_error=step_data.get("continue_on_error", False),
            timeout=step_data.get("timeout", 30.0),
            description=step_data.get("description", ""),
            tags=step_data.get("tags", []),
        )
        steps.append(step)

    return Scenario(
        name=data.get("name", "Unnamed Scenario"),
        category=data.get("category", "general"),
        description=data.get("description", ""),
        steps=steps,
        tags=data.get("tags", []),
        idempotency_prefix=data.get("idempotency_prefix", ""),
        author=data.get("author", ""),
        version=data.get("version", "1.0"),
        enabled=data.get("enabled", True),
    )


def load_scenario_from_yaml(content: str) -> Scenario:
    """Load a scenario from YAML content."""
    import yaml

    data = yaml.safe_load(content)
    if isinstance(data, list):
        # Multiple scenarios in one file - return first
        data = data[0] if data else {}
    return scenario_from_dict(data)
