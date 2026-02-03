"""
HTTP client for executing scenario steps.

Handles making HTTP requests with auth, variable substitution,
and response parsing.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from .scenario import (
    AuthRole,
    ExecutionContext,
    Scenario,
    ScenarioStep,
    StepResult,
)


def extract_json_path(data: dict | list, path: str) -> Any:
    """Extract a value from nested JSON using a simple path syntax.

    Supported syntax examples:
      - "rule_id" -> top-level field
      - "data.id" -> nested dict
      - "items[0].id" -> list index
      - "$.rule_id" -> JSONPath-style root

    Returns the found value or None.
    """
    if not path:
        return None

    # Handle JSONPath-style root
    if path.startswith("$."):
        path = path[2:]

    if not path:
        return data

    cur = data
    tokens = path.split(".")

    for tok in tokens:
        if not cur:
            return None

        # Handle array indexing: items[0]
        match = re.match(r"^(?P<key>[^\[]+)(?:\[(?P<idx>\d+)\])?$", tok)
        if not match:
            return None

        key = match.group("key")
        idx = match.group("idx")

        # Traverse
        if isinstance(cur, dict):
            if key not in cur:
                return None
            cur = cur[key]
        elif isinstance(cur, list):
            # When current node is a list, key should be an integer index
            try:
                i = int(key)
                cur = cur[i]
            except (ValueError, IndexError, KeyError):
                return None
        else:
            return None

        # Apply array index if present
        if idx is not None:
            if not isinstance(cur, list):
                return None
            try:
                cur = cur[int(idx)]
            except (ValueError, IndexError):
                return None

    return cur


class ScenarioHttpClient:
    """HTTP client for executing scenario steps."""

    def __init__(
        self,
        base_url: str,
        auth_tokens: dict[str, str | None],
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_tokens = auth_tokens
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def get_auth_header(self, role: AuthRole) -> dict[str, str] | None:
        """Get the authorization header for a role."""
        token = self.auth_tokens.get(role.value)
        if not token and role != AuthRole.NONE:
            # Try fallback to default
            token = self.auth_tokens.get("default")

        if token:
            # Normalize to Bearer format
            if not token.lower().startswith("bearer "):
                token = f"Bearer {token}"
            return {"Authorization": token}
        return None

    def execute_step(
        self,
        step: ScenarioStep,
        context: ExecutionContext,
    ) -> StepResult:
        """Execute a single scenario step."""
        start_time = time.time()
        result = StepResult(
            step_name=step.name,
            passed=False,
            skipped=False,
        )

        try:
            # Check if step should be skipped
            if step.skip_if:
                should_skip, reason = step.skip_if.should_skip(context)
                if should_skip:
                    result.skipped = True
                    result.passed = True
                    result.duration_ms = (time.time() - start_time) * 1000
                    return result

            # Build the request
            url = self.base_url + context.format_template(step.request_path)
            method = step.request_method.value

            # Get auth headers
            headers = self.get_auth_header(step.auth) or {}
            headers["Content-Type"] = "application/json"

            # Format JSON body with variables
            json_body = context.format_json(step.request_json) if step.request_json else None
            params = context.format_json(step.request_params) if step.request_params else None

            # Add idempotency key if specified
            if step.idempotency_key_template:
                idempotency_key = context.format_template(step.idempotency_key_template)
                if json_body is None:
                    json_body = {}
                json_body["idempotency_key"] = idempotency_key

            # Capture request details
            result.request_method = method
            result.request_url = url
            result.request_headers = dict(headers) if headers else None

            # Format request body for display
            if json_body:
                result.request_body = json.dumps(json_body, indent=2)
            elif params:
                result.request_body = f"params: {params}"

            # Make the request
            response = self.client.request(
                method=method,
                url=url,
                json=json_body,
                params=params,
                headers=headers,
                timeout=step.timeout,
            )

            result.status_code = response.status_code
            result.duration_ms = (time.time() - start_time) * 1000

            # Capture response headers
            result.response_headers = dict(response.headers) if response.headers else None

            # Try to parse response
            try:
                response_data = response.json()
                # Format with indent=2 like pytest HTML reports
                result.response_body_formatted = json.dumps(response_data, indent=2)
                result.response_body = result.response_body_formatted
                # Truncated summary for console
                result.response_summary = json.dumps(response_data, indent=2)[:500]
            except Exception:
                response_data = None
                result.response_body = response.text[:1000] if response.text else ""
                result.response_summary = result.response_body[:500] if result.response_body else ""

            # Handle conflict (409) with on_conflict handler
            if response.status_code == 409 and step.on_conflict:
                conflict_result = self._handle_conflict(step, context, response)
                if conflict_result:
                    # Check for skip marker
                    if conflict_result.get("_skip_conflict"):
                        # Save default values even when skipping due to conflict
                        if step.save:
                            for save_spec in step.save:
                                if save_spec.default is not None:
                                    context.set_variable(save_spec.name, str(save_spec.default))
                                    result.saved_variables[save_spec.name] = str(save_spec.default)
                        result.passed = True
                        return result
                    # Otherwise, save the fetched variables using the step's save spec names
                    if step.save:
                        for save_spec in step.save:
                            # Get the key from conflict_result that matches the json_path's last segment
                            json_path_key = (
                                save_spec.json_path.split(".")[-1] if save_spec.json_path else None
                            )
                            if json_path_key and json_path_key in conflict_result:
                                value = conflict_result[json_path_key]
                                context.set_variable(save_spec.name, value)
                                result.saved_variables[save_spec.name] = value
                    result.passed = True
                    return result

            # Validate expectations
            if step.expect:
                passed, errors = step.expect.validate(response)
                result.assertions_passed = 1
                if not passed:
                    result.assertions_failed = len(errors)
                    result.passed = False
                    result.error_message = "; ".join(errors)
                    return result

            # Save variables from response
            if step.save and response_data:
                for save_spec in step.save:
                    value = extract_json_path(response_data, save_spec.json_path)
                    if value is not None or save_spec.default is not None:
                        final_value = value if value is not None else save_spec.default

                        # Handle list conversion
                        if save_spec.as_list and isinstance(final_value, list):
                            final_value = ",".join(str(v) for v in final_value)
                        elif isinstance(final_value, list) and final_value:
                            final_value = str(final_value[0])
                        elif not isinstance(final_value, str):
                            final_value = str(final_value)

                        context.set_variable(save_spec.name, final_value)
                        result.saved_variables[save_spec.name] = final_value

            # Save response for later reference
            context.responses[step.name] = response

            result.passed = True
            return result

        except httpx.TimeoutException:
            result.duration_ms = (time.time() - start_time) * 1000
            result.error_message = f"Request timeout after {step.timeout}s"
            return result

        except httpx.HTTPStatusError as e:
            result.duration_ms = (time.time() - start_time) * 1000
            result.status_code = e.response.status_code
            result.error_message = f"HTTP error: {e}"
            # Try to capture response body
            try:
                if e.response.content:
                    result.response_body = e.response.text[:1000]
            except Exception:
                pass
            return result

        except Exception as e:
            result.duration_ms = (time.time() - start_time) * 1000
            result.error_message = f"Unexpected error: {e}"
            return result

    def _handle_conflict(
        self,
        step: ScenarioStep,
        context: ExecutionContext,
        conflict_response: httpx.Response,
    ) -> dict[str, Any]:
        """Handle a 409 conflict response using the on_conflict handler."""
        if not step.on_conflict:
            return {}

        handler = step.on_conflict

        # If skip_if_conflict, return a special marker to indicate step should be passed
        if handler.skip_if_conflict:
            # Return marker to signal caller to mark step as passed
            return {"_skip_conflict": True}

        # Otherwise, fetch the existing entity
        fetch_url = self.base_url + context.format_template(handler.fetch_path_template)
        headers = self.get_auth_header(step.auth) or {}

        try:
            fetch_response = self.client.request(
                method=handler.fetch_method,
                url=fetch_url,
                headers=headers,
                timeout=10.0,
            )

            if fetch_response.status_code == 200:
                data = fetch_response.json()
                value = extract_json_path(data, handler.save_from_jsonpath)
                if value:
                    return {handler.save_from_jsonpath.split(".")[-1]: str(value)}
        except Exception:
            pass

        return {}


class ScenarioExecutor:
    """Executes complete scenarios with all steps."""

    def __init__(
        self,
        base_url: str,
        auth_tokens: dict[str, str | None],
        db_connection: Any = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url
        self.auth_tokens = auth_tokens
        self.db_connection = db_connection
        self.timeout = timeout
        self.http_client = ScenarioHttpClient(base_url, auth_tokens, timeout)

    def close(self) -> None:
        """Close resources."""
        self.http_client.close()

    def execute_scenario(self, scenario: Scenario) -> StepResult:
        """Execute a complete scenario.

        Returns a StepResult with aggregate results.
        """
        start_time = time.time()

        context = ExecutionContext(
            auth_tokens=self.auth_tokens,
            http_client=self.http_client.client,
            db_connection=self.db_connection,
        )

        # Initialize common variables
        context.set_variable("ts", str(int(time.time())))
        context.set_variable("run_id", str(int(time.time() * 1000)))
        context.set_variable("scenario_name", scenario.name)
        context.set_variable("category", scenario.category)

        step_results = []
        steps_passed = 0
        steps_failed = 0
        steps_skipped = 0

        for step in scenario.steps:
            result = self.http_client.execute_step(step, context)
            step_results.append(result)

            if result.skipped:
                steps_skipped += 1
            elif result.passed:
                steps_passed += 1
            else:
                steps_failed += 1
                # Stop on failure unless continue_on_error
                if not step.continue_on_error:
                    break

        duration_ms = (time.time() - start_time) * 1000

        # Return aggregate result
        aggregate = StepResult(
            step_name=scenario.name,
            passed=steps_failed == 0,
            skipped=False,
            duration_ms=duration_ms,
            steps_passed=steps_passed,
            steps_failed=steps_failed,
            assertions_passed=sum(r.assertions_passed for r in step_results),
            assertions_failed=sum(r.assertions_failed for r in step_results),
        )

        # Store step results for reporting
        aggregate.saved_variables = {"_step_results": step_results}

        return aggregate
