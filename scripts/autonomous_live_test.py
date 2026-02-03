#!/usr/bin/env python3
"""
Autonomous Live Test Suite - Local-Only API Validation Harness

This script provides idempotent, repeatable API testing against a running local server.
It is designed to be run by AI coding agents after making code changes.

Key features:
- Local-only safety guards (APP_ENV must be 'local')
- Idempotent operations (can run N times with identical results)
- Rinse/repeat mode for consistency validation
- YAML-based scenario definitions
- Multi-layer validation (HTTP, OpenAPI, domain invariants, side effects)
- HTML + JSON reporting

Usage:
    uv run autonomous-live-test                    # Single run
    uv run autonomous-live-test --reset            # Full DB reset first
    uv run autonomous-live-test --rinse-repeat 5   # Run 5 times, check consistency
    uv run autonomous-live-test --scenarios smoke,governance

Safety:
- Requires APP_ENV=local
- Requires Doppler config 'local'
- Requires DB host to be localhost or explicit --i-know-this-is-local flag
- Never runs against test/prod Doppler configs

Exit codes:
    0: All scenarios passed
    1: One or more scenarios failed
    2: Prerequisites failed (Docker, Doppler, etc.)
    3: Safety guard triggered (not local)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import yaml

# Add app to path for imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import autonomous testing library
from scripts.autonomous_lib import (  # noqa: E402 (import after path setup)
    ScenarioExecutor,
    scenario_from_dict,
)


class ExitCode(Enum):
    """Exit codes for the test harness."""

    SUCCESS = 0
    TESTS_FAILED = 1
    PREREQUISITES_FAILED = 2
    SAFETY_TRIGGERED = 3


@dataclass
class TestConfig:
    """Configuration for the test run."""

    base_url: str = "http://127.0.0.1:8000"
    request_timeout: float = 30.0
    server_ready_timeout: int = 60
    artifacts_dir: Path = field(default_factory=lambda: Path("artifacts/autonomous-live-tests"))
    doppler_config: str = "local"
    i_know_this_is_local: bool = False
    reset_db: bool = False
    cleanup: bool = False
    rinse_repeat: int = 1
    scenarios_filter: list[str] = field(default_factory=list)
    verbose: bool = False
    # S3 config (loaded from environment/Doppler)
    s3_endpoint_url: str | None = None
    s3_bucket_name: str = "fraud-gov-artifacts"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    def __post_init__(self):
        # Load S3 config from environment
        import os

        self.s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL", self.s3_endpoint_url)
        self.s3_bucket_name = os.environ.get("S3_BUCKET_NAME", self.s3_bucket_name)
        self.s3_access_key_id = os.environ.get("S3_ACCESS_KEY_ID", self.s3_access_key_id)
        self.s3_secret_access_key = os.environ.get(
            "S3_SECRET_ACCESS_KEY", self.s3_secret_access_key
        )
        # Create timestamped artifacts directory
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self.run_dir = self.artifacts_dir / timestamp
        self.run_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class ScenarioResult:
    """Result of running a single scenario."""

    name: str
    passed: bool
    category: str = ""  # Category from scenario
    steps_total: int = 0
    steps_passed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    duration_ms: float = 0.0
    error_message: str = ""
    artifacts: list[str] = field(default_factory=list)
    # Step execution details for reporting
    step_details: list[Any] = field(default_factory=list)  # List of StepResult


@dataclass
class RunSummary:
    """Summary of a complete test run."""

    run_number: int
    scenarios_passed: int = 0
    scenarios_failed: int = 0
    scenarios_total: int = 0
    steps_passed: int = 0
    steps_failed: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    duration_ms: float = 0.0
    scenario_results: list[ScenarioResult] = field(default_factory=list)


def log(msg: str, level: str = "info") -> None:
    """Log a message with timestamp."""
    timestamp = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
    prefix = {
        "info": "[INFO]",
        "warn": "[WARN]",
        "error": "[ERROR]",
        "success": "[OK]",
        "debug": "[DEBUG]",
    }.get(level, "[LOG]")
    print(f"{timestamp} {prefix} {msg}")


def verify_prerequisites(config: TestConfig) -> tuple[bool, str]:
    """Verify that all prerequisites are met.

    Returns (success, error_message).
    """
    # 1. Check APP_ENV
    app_env = os.environ.get("APP_ENV", "")
    if app_env != "local":
        if not config.i_know_this_is_local:
            return (
                False,
                f"APP_ENV is '{app_env}', must be 'local'. Use --i-know-this-is-local to override.",
            )

    # 2. Check we're not using test/prod Doppler configs
    current_doppler_config = os.environ.get("DOPPLER_CONFIG", config.doppler_config)
    if current_doppler_config in ("test", "prod", "ci"):
        return (
            False,
            f"DOPPLER_CONFIG is '{current_doppler_config}'. This harness only runs with 'local' config.",
        )

    # 3. Check DATABASE_URL host is local (unless explicitly overridden)
    db_url = os.environ.get("DATABASE_URL_APP", "")
    if db_url and not config.i_know_this_is_local:
        # Extract host from database URL
        match = re.search(r"@([^:/]+)", db_url)
        if match:
            host = match.group(1)
            if host not in ("localhost", "127.0.0.1", "host.docker.internal"):
                return (
                    False,
                    f"DATABASE_URL_APP host is '{host}'. Must be localhost. Use --i-know-this-is-local to override.",
                )

    # 4. Check Docker is available (for local DB/MinIO)
    try:
        result = subprocess.run(
            ["docker", "version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return (
                False,
                "Docker is not running. Local testing requires Docker for PostgreSQL and MinIO.",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (
            False,
            "Docker is not available. Local testing requires Docker for PostgreSQL and MinIO.",
        )

    # 5. Check Doppler CLI is available
    try:
        result = subprocess.run(
            ["doppler", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "Doppler CLI is not available."
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Doppler CLI is not available."

    log("All prerequisites verified", "success")
    return True, ""


def start_local_infrastructure(config: TestConfig) -> bool:
    """Start local infrastructure (PostgreSQL + MinIO) if not already running."""
    # Check what's already running
    status = check_infrastructure_status()
    started = []

    if not status["postgres"]:
        log("Starting PostgreSQL...")
        cmd = ["uv", "run", "db-local-up"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                started.append("PostgreSQL")
            else:
                log(f"Failed to start PostgreSQL: {result.stderr}", "error")
                return False
        except Exception as e:
            log(f"Error starting PostgreSQL: {e}", "error")
            return False
    else:
        log("PostgreSQL already running (skipping)")

    if not status["minio"]:
        log("Starting MinIO...")
        cmd = ["uv", "run", "objstore-local-up"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                started.append("MinIO")
            else:
                log(f"Failed to start MinIO: {result.stderr}", "error")
                return False
        except Exception as e:
            log(f"Error starting MinIO: {e}", "error")
            return False
    else:
        log("MinIO already running (skipping)")

    if started:
        log(f"Local infrastructure started: {', '.join(started)}", "success")
    else:
        log("Local infrastructure already running (no action needed)", "success")
    return True


def reset_database(config: TestConfig) -> bool:
    """Clean up test data (truncate tables only, no schema changes)."""
    log("Cleaning up test data (truncating tables)...")

    # This only truncates tables, preserves schema
    return cleanup_test_data(config)


def check_infrastructure_status() -> dict[str, bool]:
    """Check if PostgreSQL and MinIO containers are already running."""
    status = {"postgres": False, "minio": False}
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            containers = result.stdout.lower()
            status["postgres"] = "fraud-gov-postgres" in containers
            status["minio"] = "fraud-gov-minio" in containers
    except Exception:
        pass
    return status


def get_doppler_secret(secret_name: str) -> str | None:
    """Fetch a secret from Doppler CLI."""
    try:
        result = subprocess.run(
            ["doppler", "secrets", "get", secret_name, "--plain"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def fetch_database_admin_url() -> str | None:
    """Fetch DATABASE_URL_ADMIN from Doppler."""
    return get_doppler_secret("DATABASE_URL_ADMIN")


def cleanup_test_data(config: TestConfig) -> bool:
    """Clean up test data (truncate tables only, no schema changes, no reseed).

    IMPORTANT: Only truncates tables belonging to THIS project (rule-management).
    Does NOT touch transactional_* tables from other projects.
    """
    log("Cleaning up test data (rule-management tables only)...")

    # Fetch admin URL from Doppler if not in environment
    admin_url = os.environ.get("DATABASE_URL_ADMIN", "")
    if not admin_url:
        admin_url = fetch_database_admin_url()

    if not admin_url:
        log("DATABASE_URL_ADMIN not found, cannot cleanup", "error")
        return False

    # Store for future use in this run
    os.environ["DATABASE_URL_ADMIN"] = admin_url

    # Tables belonging to this project (rule-management), in dependency order
    # NO transactional_* tables - those belong to other projects!
    our_tables = [
        "audit_log",
        "approvals",
        "ruleset_version_rules",
        "ruleset_versions",
        "ruleset_manifest",
        "rulesets",
        "rule_versions",
        "rules",
    ]

    try:
        import psycopg

        with psycopg.connect(admin_url, autocommit=True) as conn:
            for table in our_tables:
                try:
                    full_table: str = f"fraud_gov.{table}"
                    # psycopg accepts plain SQL strings - type error is false ALLOWLIST
                    conn.execute(f"TRUNCATE TABLE {full_table} CASCADE;")  # type: ignore[arg-type]
                    log(f"  Truncated {full_table}", "info")
                except psycopg.Error as e:
                    table_name = getattr(e, "table", table) or table
                    log(f"  Warning: Could not truncate fraud_gov.{table_name}: {e}", "warn")

        log("Test data cleanup complete (transactional_* tables preserved)", "success")
        return True
    except BaseException as e:
        log(f"Error cleaning up test data: {e}", "error")
        return False


def cleanup_s3_artifacts(config: TestConfig) -> bool:
    """Clean up S3/MinIO artifacts from test runs."""
    log("Cleaning up S3 artifacts...")

    try:
        import boto3
        from botocore.config import Config

        if not config.s3_endpoint_url or not config.s3_access_key_id:
            log("S3 not configured, skipping cleanup", "warn")
            return True

        s3 = boto3.client(
            "s3",
            endpoint_url=config.s3_endpoint_url,
            aws_access_key_id=config.s3_access_key_id,
            aws_secret_access_key=config.s3_secret_access_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        paginator = s3.get_paginator("list_objects_v2")
        deleted_count = 0
        for page in paginator.paginate(Bucket=config.s3_bucket_name):
            if "Contents" in page:
                for obj in page["Contents"]:
                    s3.delete_object(Bucket=config.s3_bucket_name, Key=obj["Key"])
                    deleted_count += 1

        log(f"Deleted {deleted_count} S3 objects", "success")
        return True
    except Exception as e:
        log(f"Error cleaning up S3 artifacts: {e}", "error")
        return False


def start_server(config: TestConfig) -> subprocess.Popen | None:
    """Start the development server via Doppler."""
    log("Starting development server...")

    # Use doppler run to inject secrets
    cmd = [
        "doppler",
        "run",
        "--project=card-fraud-rule-management",
        "--config=local",
        "--",
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        # No --reload for stability in autonomous testing
    ]

    # Create log file for server output
    server_log = config.run_dir / "server.log"
    server_log_file = open(server_log, "w")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=server_log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log(f"Server started (PID {proc.pid}), logging to {server_log}")
        return proc
    except Exception as e:
        log(f"Failed to start server: {e}", "error")
        server_log_file.close()
        return None


def wait_for_server_ready(config: TestConfig) -> bool:
    """Wait for the server to be ready."""
    log(f"Waiting for server readiness at {config.base_url}/api/v1/health...")

    deadline = time.time() + config.server_ready_timeout
    client = httpx.Client()

    while time.time() < deadline:
        try:
            r = client.get(f"{config.base_url}/api/v1/health", timeout=2.0)
            if r.status_code == 200:
                log("Server is ready", "success")
                return True
        except Exception:
            pass
        time.sleep(0.5)

    log("Server readiness timeout", "error")
    return False


def stop_server(proc: subprocess.Popen) -> None:
    """Stop the development server."""
    if not proc:
        return

    log(f"Stopping server (PID {proc.pid})...")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log("Server stopped", "success")
    except Exception as e:
        log(f"Error stopping server: {e}", "warn")


def load_scenarios(scenarios_dir: Path) -> list[dict[str, Any]]:
    """Load all scenario YAML files from the directory."""
    scenarios = []

    if not scenarios_dir.exists():
        log(f"Scenarios directory not found: {scenarios_dir}", "warn")
        return scenarios

    for path in scenarios_dir.glob("*.yaml"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, list):
                    scenarios.extend(data)
                elif isinstance(data, dict):
                    scenarios.append(data)
                # Store the source file path
                if scenarios:
                    scenarios[-1].setdefault("_source_file", str(path))
        except Exception as e:
            log(f"Failed to load scenario from {path}: {e}", "error")

    return scenarios


def filter_scenarios(
    scenarios: list[dict[str, Any]],
    filter_list: list[str],
) -> list[dict[str, Any]]:
    """Filter scenarios by category/name."""
    if not filter_list:
        return scenarios

    filtered = []
    for scenario in scenarios:
        category = scenario.get("category", "")
        name = scenario.get("name", "")
        tags = scenario.get("tags", [])

        # Check if any filter matches
        for f in filter_list:
            if f.lower() in category.lower() or f.lower() in name.lower():
                filtered.append(scenario)
                break
            elif any(f.lower() in str(t).lower() for t in tags):
                filtered.append(scenario)
                break

    return filtered


def fetch_auth0_user_token(
    *,
    domain: str,
    audience: str,
    client_id: str,
    client_secret: str,
    username: str,
    password: str,
    connection: str = "Username-Password-Authentication",
) -> str | None:
    """Fetch an Auth0 access token via Resource Owner Password Credentials grant.

    This is used to get tokens for specific test users (maker, checker, admin)
    to properly test maker-checker workflows where maker != checker.
    """
    url = f"https://{domain}/oauth/token"
    payload = {
        "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
        "client_id": client_id,
        "username": username,
        "password": password,
        "audience": audience,
        "scope": "openid profile email",
        "realm": connection,
    }
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            log(f"Auth0 token response missing access_token for {username}", "warn")
            return None
        return f"Bearer {token}"
    except Exception as e:
        log(f"Failed to fetch Auth0 token for {username}: {e}", "warn")
        return None


def fetch_auth0_token(*, domain: str, audience: str, client_id: str, client_secret: str) -> str:
    """Fetch an Auth0 access token via Client Credentials grant (M2M)."""
    url = f"https://{domain}/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": audience,
    }
    r = httpx.post(url, json=payload, timeout=10.0)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Auth0 token response missing access_token")
    return f"Bearer {token}"


def initialize_auth_tokens(config: TestConfig) -> dict[str, str | None]:
    """Initialize auth tokens for different roles.

    For maker-checker workflows, we need SEPARATE tokens for maker and checker.
    We prefer user tokens (via password grant) over M2M tokens.

    IMPORTANT: This requires a test Auth0 client with password grant enabled.
    The default M2M client only has client_credentials grant (security best practice).

    To enable full testing, create a test client in Auth0 with:
    - Grant Types: Password, Client Credentials
    - Allowed APIs: Fraud Rule Management API
    - Users: test-rule-maker, test-rule-checker, test-platform-admin
    """
    tokens: dict[str, str | None] = {
        "default": None,
        "maker": None,
        "checker": None,
        "admin": None,
    }

    domain = get_doppler_secret("AUTH0_DOMAIN") or os.environ.get("AUTH0_DOMAIN", "")
    audience = get_doppler_secret("AUTH0_AUDIENCE") or os.environ.get("AUTH0_AUDIENCE", "")

    m2m_client_id = get_doppler_secret("AUTH0_CLIENT_ID") or os.environ.get("AUTH0_CLIENT_ID", "")
    m2m_client_secret = get_doppler_secret("AUTH0_CLIENT_SECRET") or os.environ.get(
        "AUTH0_CLIENT_SECRET", ""
    )

    test_client_id = os.environ.get("AUTH0_TEST_CLIENT_ID", "")
    test_client_secret = os.environ.get("AUTH0_TEST_CLIENT_SECRET", "")

    maker_password = get_doppler_secret("TEST_USER_RULE_MAKER_PASSWORD") or ""
    checker_password = get_doppler_secret("TEST_USER_RULE_CHECKER_PASSWORD") or ""
    admin_password = get_doppler_secret("TEST_USER_PLATFORM_ADMIN_PASSWORD") or ""

    if not all([domain, audience]):
        log("Auth0 credentials not configured, running without auth", "warn")
        return tokens

    fetched_any = False

    if test_client_id and test_client_secret and maker_password:
        token = fetch_auth0_user_token(
            domain=domain,
            audience=audience,
            client_id=test_client_id,
            client_secret=test_client_secret,
            username="test-rule-maker@fraud-platform.test",
            password=maker_password,
        )
        if token:
            tokens["maker"] = token
            fetched_any = True
            log("Obtained Auth0 token for maker (test-rule-maker)", "success")
        else:
            log(
                "Failed to get maker token - check AUTH0_TEST_CLIENT_ID/SECRET and password grant",
                "warn",
            )

    if test_client_id and test_client_secret and checker_password:
        token = fetch_auth0_user_token(
            domain=domain,
            audience=audience,
            client_id=test_client_id,
            client_secret=test_client_secret,
            username="test-rule-checker@fraud-platform.test",
            password=checker_password,
        )
        if token:
            tokens["checker"] = token
            fetched_any = True
            log("Obtained Auth0 token for checker (test-rule-checker)", "success")

    if test_client_id and test_client_secret and admin_password:
        token = fetch_auth0_user_token(
            domain=domain,
            audience=audience,
            client_id=test_client_id,
            client_secret=test_client_secret,
            username="test-platform-admin@fraud-platform.test",
            password=admin_password,
        )
        if token:
            tokens["admin"] = token
            fetched_any = True

    if m2m_client_id and m2m_client_secret and not fetched_any:
        try:
            token = fetch_auth0_token(
                domain=domain,
                audience=audience,
                client_id=m2m_client_id,
                client_secret=m2m_client_secret,
            )
            for key in tokens:
                tokens[key] = token
            log("Obtained Auth0 M2M token (fallback - maker=checker for approval)", "warn")
            log(
                "NOTE: For full publish testing, set AUTH0_TEST_CLIENT_ID/SECRET with password grant",
                "warn",
            )
        except Exception as e:
            log(f"Failed to fetch M2M token: {e}", "warn")

    if not any(tokens.values()):
        log("No Auth0 tokens obtained, running without auth", "warn")

    return tokens


def run_scenario(
    scenario: dict[str, Any],
    config: TestConfig,
    tokens: dict[str, str | None],
    run_dir: Path,
) -> ScenarioResult:
    """Run a single scenario and return the result."""
    name = scenario.get("name", "Unknown")
    scenario.get("category", "general")
    log(f"Running scenario: {name}")

    start_time = time.time()

    try:
        # Parse scenario from dict
        scenario_obj = scenario_from_dict(scenario)

        # Skip disabled scenarios
        if not scenario_obj.enabled:
            log(f"  Scenario '{name}' is disabled, skipping", "warn")
            return ScenarioResult(
                name=name,
                category=scenario_obj.category,
                passed=True,
                steps_total=0,
                steps_passed=0,
                steps_failed=0,
                steps_skipped=0,
                duration_ms=0,
            )

        # Create executor
        executor = ScenarioExecutor(
            base_url=config.base_url,
            auth_tokens=tokens,
            timeout=config.request_timeout,
        )

        # Execute scenario
        try:
            result = executor.execute_scenario(scenario_obj)

            # Extract step results from saved_variables
            step_results = result.saved_variables.get("_step_results", [])

            # Convert library result to our result format
            return ScenarioResult(
                name=name,
                category=scenario_obj.category,
                passed=result.passed,
                steps_total=len(scenario_obj.steps),
                steps_passed=result.steps_passed,
                steps_failed=result.steps_failed,
                steps_skipped=result.steps_skipped,
                duration_ms=result.duration_ms,
                error_message="" if result.passed else "One or more steps failed",
                artifacts=[],
                step_details=step_results,  # Include detailed step results
            )
        finally:
            executor.close()

    except Exception as e:
        log(f"  Error executing scenario '{name}': {e}", "error")
        return ScenarioResult(
            name=name,
            category=scenario_obj.category if scenario_obj else "",
            passed=False,
            steps_total=0,
            steps_passed=0,
            steps_failed=1,
            steps_skipped=0,
            duration_ms=(time.time() - start_time) * 1000,
            error_message=str(e),
        )


def run_all_scenarios(
    scenarios: list[dict[str, Any]],
    config: TestConfig,
    tokens: dict[str, str | None],
    run_number: int = 1,
) -> RunSummary:
    """Run all scenarios and return the summary."""
    summary = RunSummary(run_number=run_number, scenarios_total=len(scenarios))

    log(f"\n{'=' * 60}")
    log(f"Phase 2: Scenario Execution (Run {run_number})")
    log(f"{'=' * 60}")

    for i, scenario in enumerate(scenarios, 1):
        category = scenario.get("category", "general")
        name = scenario.get("name", f"Scenario {i}")

        result = run_scenario(scenario, config, tokens, config.run_dir / f"run_{run_number}")
        summary.scenario_results.append(result)

        if result.passed:
            summary.scenarios_passed += 1
            summary.steps_passed += result.steps_passed
            log(
                f"  [{i}/{len(scenarios)}] [{category}] {name}: PASSED ({result.steps_passed} steps)",
                "success",
            )
        else:
            summary.scenarios_failed += 1
            summary.steps_failed += result.steps_failed
            log(
                f"  [{i}/{len(scenarios)}] [{category}] {name}: FAILED - {result.error_message}",
                "error",
            )

        summary.steps_passed += result.steps_passed
        summary.steps_failed += result.steps_failed

    summary.end_time = datetime.now(UTC)
    summary.duration_ms = (summary.end_time - summary.start_time).total_seconds() * 1000

    return summary


def compare_summaries(summaries: list[RunSummary]) -> tuple[bool, str]:
    """Compare multiple run summaries for consistency."""
    if len(summaries) < 2:
        return True, "Only one run, no comparison needed"

    first = summaries[0]
    inconsistencies = []

    for i, summary in enumerate(summaries[1:], 2):
        # Compare scenario counts
        if summary.scenarios_total != first.scenarios_total:
            inconsistencies.append(
                f"Run {i}: scenarios_total mismatch ({summary.scenarios_total} vs {first.scenarios_total})"
            )

        # Compare passed/failed counts
        if summary.scenarios_passed != first.scenarios_passed:
            inconsistencies.append(
                f"Run {i}: scenarios_passed mismatch ({summary.scenarios_passed} vs {first.scenarios_passed})"
            )

        if summary.scenarios_failed != first.scenarios_failed:
            inconsistencies.append(
                f"Run {i}: scenarios_failed mismatch ({summary.scenarios_failed} vs {first.scenarios_failed})"
            )

    if inconsistencies:
        return False, "; ".join(inconsistencies)

    return True, "All runs produced identical results"


def generate_report(summaries: list[RunSummary], config: TestConfig) -> None:
    """Generate the summary.json and report.html files."""
    log("Generating reports...")

    # Import the enhanced reporter
    from scripts.autonomous_lib.reporter import (
        EnhancedHtmlReporter,
        ScenarioExecutionDetail,
        TestRunDetail,
    )

    # Generate summary.json
    summary_data = {
        "timestamp": datetime.now(UTC).isoformat(),
        "runs_completed": len(summaries),
        "consistency_check": "passed" if len(summaries) < 2 else compare_summaries(summaries)[0],
        "runs": [
            {
                "run_number": s.run_number,
                "scenarios_total": s.scenarios_total,
                "scenarios_passed": s.scenarios_passed,
                "scenarios_failed": s.scenarios_failed,
                "steps_passed": s.steps_passed,
                "steps_failed": s.steps_failed,
                "duration_ms": s.duration_ms,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "end_time": s.end_time.isoformat() if s.end_time else None,
            }
            for s in summaries
        ],
    }

    summary_path = config.run_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    log(f"Summary written to {summary_path}", "success")

    # Build TestRunDetail objects for enhanced reporter
    test_runs = []
    for summary in summaries:
        scenario_details = []
        for scenario_result in summary.scenario_results:
            # Convert step_details to dict format for reporter
            step_dicts = []
            for step in scenario_result.step_details:
                if hasattr(step, "__dict__"):
                    # Convert dataclass to dict
                    step_dict = {
                        "step_name": step.step_name,
                        "passed": step.passed,
                        "skipped": step.skipped,
                        "status_code": step.status_code,
                        "duration_ms": step.duration_ms,
                        "error_message": step.error_message,
                        "request_method": getattr(step, "request_method", ""),
                        "request_url": getattr(step, "request_url", ""),
                        "request_headers": getattr(step, "request_headers", None),
                        "request_body": getattr(step, "request_body", None),
                        "response_headers": getattr(step, "response_headers", None),
                        "response_body": getattr(step, "response_body_formatted", None)
                        or getattr(step, "response_body", None),
                    }
                else:
                    step_dict = step
                step_dicts.append(step_dict)

            scenario_details.append(
                ScenarioExecutionDetail(
                    scenario_name=scenario_result.name,
                    category=scenario_result.category,
                    passed=scenario_result.passed,
                    duration_ms=scenario_result.duration_ms,
                    steps_total=scenario_result.steps_total,
                    steps_passed=scenario_result.steps_passed,
                    steps_failed=scenario_result.steps_failed,
                    steps_skipped=scenario_result.steps_skipped,
                    step_details=step_dicts,
                )
            )

        test_runs.append(
            TestRunDetail(
                run_number=summary.run_number,
                start_time=summary.start_time,
                end_time=summary.end_time,
                duration_ms=summary.duration_ms,
                scenarios_total=summary.scenarios_total,
                scenarios_passed=summary.scenarios_passed,
                scenarios_failed=summary.scenarios_failed,
                scenario_details=scenario_details,
                base_url=config.base_url,
                doppler_config=config.doppler_config,
            )
        )

    # Generate HTML report using enhanced reporter
    html_path = config.run_dir / "report.html"
    reporter = EnhancedHtmlReporter()
    reporter.generate_report(test_runs, html_path)

    log(f"HTML report written to {html_path}", "success")


def print_summary(summaries: list[RunSummary], config: TestConfig) -> None:
    """Print a formatted summary to console."""
    if not summaries:
        log("No test runs completed", "error")
        return

    first = summaries[0]

    print("\n" + "=" * 60)
    print("AUTONOMOUS LIVE TEST SUITE")
    print("=" * 60)
    print(f"Environment: local (Doppler config: {config.doppler_config})")
    print(f"Artifacts: {config.run_dir}")
    print()

    print("Phase 1: Preconditions")
    print("  [OK] Docker running")
    print("  [OK] PostgreSQL responding")
    print("  [OK] MinIO responding")
    print("  [OK] Doppler secrets loaded")
    print("  [OK] Server started")
    print()

    if config.reset_db:
        print("  [OK] Database reset")
        print()

    print(f"Phase 2: Scenario Execution ({len(summaries)} run{'s' if len(summaries) > 1 else ''})")
    print(f"  Scenarios: {first.scenarios_total}")
    print(f"  Passed: {first.scenarios_passed}")
    print(f"  Failed: {first.scenarios_failed}")
    print(f"  Steps Passed: {first.steps_passed}")
    print(f"  Steps Failed: {first.steps_failed}")

    if len(summaries) > 1:
        consistency_ok, msg = compare_summaries(summaries)
        print()
        print("Phase 3: Rinse/Repeat Consistency")
        for i, s in enumerate(summaries[1:], 2):
            print(f"  Run {i}: {s.scenarios_passed}/{s.scenarios_total} passed")
        print(f"  Consistency: {'100%' if consistency_ok else 'FAILED'}")

    print()
    print("Phase 4: Report Generation")
    print(f"  [OK] {config.run_dir / 'summary.json'}")
    print(f"  [OK] {config.run_dir / 'report.html'}")
    print()

    result = "ALL PASSED" if first.scenarios_failed == 0 else "SOME FAILED"
    total_executions = sum(s.scenarios_total for s in summaries)
    print(
        f"Result: {result} ({first.scenarios_total} scenarios × {len(summaries)} runs = {total_executions} executions)"
    )
    print("=" * 60)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous Live Test Suite - Local-Only API Validation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run autonomous-live-test                    # Single run
  uv run autonomous-live-test --reset            # Full DB reset first
  uv run autonomous-live-test --rinse-repeat 5   # Run 5 times
  uv run autonomous-live-test --scenarios smoke,governance
        """,
    )

    parser.add_argument(
        "--base-url",
        type=str,
        default="http://127.0.0.1:8000",
        help="Base URL for the API (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--no-server",
        action="store_true",
        help="Don't start server (assume it's already running)",
    )
    parser.add_argument(
        "--no-infra",
        action="store_true",
        help="Don't start infrastructure (assume DB/MinIO are running)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset database schema before running (destructive)",
    )
    parser.add_argument(
        "--i-know-this-is-local",
        action="store_true",
        help="Override safety checks (use with caution)",
    )
    parser.add_argument(
        "--rinse-repeat",
        type=int,
        default=1,
        metavar="N",
        help="Run tests N times, resetting data before each run for clean slate reproducibility",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default="",
        help="Comma-separated list of scenario categories/names to run",
    )
    parser.add_argument(
        "--scenarios-dir",
        type=str,
        default=str(ROOT / "scripts/autonomous_scenarios"),
        help="Directory containing scenario YAML files",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up test data and artifacts after running (default: False, keeps data for verification)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    config = TestConfig(
        base_url=args.base_url,
        request_timeout=args.timeout,
        i_know_this_is_local=args.i_know_this_is_local,
        reset_db=args.reset,
        cleanup=args.cleanup,
        rinse_repeat=args.rinse_repeat,
        scenarios_filter=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        verbose=args.verbose,
    )

    print("=" * 60)
    print("AUTONOMOUS LIVE TEST SUITE")
    print("=" * 60)
    print(f"Environment: local (Doppler config: {config.doppler_config})")
    print(f"Base URL: {config.base_url}")
    print(f"Runs: {config.rinse_repeat}")
    print("=" * 60)
    print()

    # Phase 0: Prerequisites and safety checks
    log("Phase 0: Prerequisites")
    success, error = verify_prerequisites(config)
    if not success:
        log(f"Safety check failed: {error}", "error")
        log("This harness only runs in local environment to protect production data.", "error")
        return ExitCode.SAFETY_TRIGGERED.value

    # Phase 1: Environment setup
    log("\nPhase 1: Environment Setup")

    server_proc = None
    summaries = []

    try:
        # Start infrastructure if needed
        if not args.no_infra:
            if not start_local_infrastructure(config):
                return ExitCode.PREREQUISITES_FAILED.value

        # Reset database if requested
        if config.reset_db:
            if not reset_database(config):
                return ExitCode.PREREQUISITES_FAILED.value

        # Start server if needed
        if not args.no_server:
            server_proc = start_server(config)
            if not server_proc:
                return ExitCode.PREREQUISITES_FAILED.value

            if not wait_for_server_ready(config):
                log("Server failed to become ready", "error")
                return ExitCode.PREREQUISITES_FAILED.value

        # Initialize auth tokens
        tokens = initialize_auth_tokens(config)

        # Load scenarios
        scenarios_dir = Path(args.scenarios_dir)
        scenarios = load_scenarios(scenarios_dir)
        scenarios = filter_scenarios(scenarios, config.scenarios_filter)

        if not scenarios:
            log("No scenarios to run", "warn")
        else:
            log(f"Loaded {len(scenarios)} scenario(s)")

        # Run scenarios (possibly multiple times with reset before each run)
        for run_num in range(1, config.rinse_repeat + 1):
            # Reset data before EACH run for clean slate reproducibility
            # This ensures every run starts with identical state
            if run_num > 1 or config.reset_db:
                log(f"\n[Run {run_num}] Resetting data for clean slate...")
                if not reset_database(config):
                    return ExitCode.PREREQUISITES_FAILED.value
                # Also cleanup S3 artifacts for clean slate
                cleanup_s3_artifacts(config)

            summary = run_all_scenarios(scenarios, config, tokens, run_num)
            summaries.append(summary)

            # If first run failed, don't continue
            if run_num == 1 and summary.scenarios_failed > 0:
                log("First run had failures, stopping rinse/repeat", "warn")
                break

        # Generate reports
        generate_report(summaries, config)

        # Print summary
        print_summary(summaries, config)

        # Cleanup if requested (at END, after user has had chance to verify)
        if config.cleanup:
            log("\nPhase 5: Cleanup")
            cleanup_test_data(config)
            cleanup_s3_artifacts(config)
            log("Cleanup complete", "success")

        # Exit with appropriate code
        if summaries and summaries[0].scenarios_failed > 0:
            return ExitCode.TESTS_FAILED.value

        return ExitCode.SUCCESS.value

    except KeyboardInterrupt:
        log("\nInterrupted by user", "warn")
        return ExitCode.PREREQUISITES_FAILED.value

    finally:
        # Always stop the server if we started it
        if server_proc and not args.no_server:
            stop_server(server_proc)


if __name__ == "__main__":
    sys.exit(main())
