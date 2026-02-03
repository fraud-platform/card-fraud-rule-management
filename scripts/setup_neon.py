#!/usr/bin/env python3
"""
Neon project and branch automation.

Usage:
    # Delete existing project and start fresh
    doppler run --config local -- uv run python scripts/setup_neon.py --delete-project --yes

    # Create project with branches and compute endpoints (automated)
    doppler run --config local -- uv run python scripts/setup_neon.py --yes --create-compute

What it does:
1. Creates Neon project (if not exists) with PostgreSQL 18
2. Creates 'test' branch (if not exists)
    3. Creates 'prod' branch (if not exists)
4. Creates compute endpoints for each branch (if --create-compute specified)
5. Gets connection info (host, neondb_owner password) via Neon API

CRITICAL - Password Workflow (READ THIS):
    Each Doppler config (local, test, prod) has its OWN UNIQUE passwords:
    - FRAUD_GOV_APP_PASSWORD (unique per environment)
    - FRAUD_GOV_ANALYTICS_PASSWORD (unique per environment)

    DATABASE_URL_* in each Doppler config MUST use that environment's passwords.
    This script outputs connection STRINGS with PLACEHOLDERS - you must replace
    {FRAUD_GOV_APP_PASSWORD} and {FRAUD_GOV_ANALYTICS_PASSWORD} with the actual
    values from THAT environment's Doppler config.

    CORRECT WORKFLOW:
    1. Run setup_neon.py (this script) - it outputs hostnames
    2. For EACH environment (test, prod):
       a. Get FRAUD_GOV_APP_PASSWORD from that Doppler config
       b. Get FRAUD_GOV_ANALYTICS_PASSWORD from that Doppler config
       c. Update DATABASE_URL_* with THOSE passwords + the hostname from this script

Environment Mapping:
    - Local Docker     -> local Doppler config -> localhost:5432
    - Neon test branch -> test Doppler config  -> <test_endpoint_host>
    - Neon prod branch -> prod Doppler config  -> <prod_endpoint_host>

Requirements:
    - NEON_API_KEY in environment (from Doppler 'local' config) - Use organization API key
    - httpx (already in project dependencies)

PostgreSQL Version: 18 (native UUIDv7 support)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

import httpx

# Neon API endpoints
NEON_API_BASE = "https://console.neon.tech/api/v2"
PROJECT_NAME = "fraud-governance"


@dataclass
class NeonConnectionInfo:
    """Connection information for a Neon branch."""

    branch_name: str
    database_name: str
    host: str
    owner_password: str
    app_user: str = "fraud_gov_app_user"
    analytics_user: str = "fraud_gov_analytics_user"


class NeonSetupError(Exception):
    """Error during Neon setup."""


def _request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int = 60,
    sleep_seconds: float = 2.0,
    **kwargs,
) -> httpx.Response:
    """Neon API occasionally returns 423 while provisioning resources.

    Treat 423 as a transient state and retry with a short backoff.
    """
    last_response: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        response = client.request(method, url, **kwargs)
        last_response = response
        if response.status_code != 423:
            response.raise_for_status()
            return response

        if attempt == 1 or attempt % 10 == 0:
            try:
                details = response.json()
            except Exception:
                details = response.text
            print(
                f"  [WAIT] Neon provisioning in progress (423). Retrying... attempt {attempt}/{max_attempts}"
            )
            if details:
                print(f"         {details}")

        time.sleep(sleep_seconds)

    # Exhausted retries
    if last_response is not None:
        last_response.raise_for_status()
    raise NeonSetupError("Neon API request failed and no response was received")


def get_neon_api_key() -> str:
    """Get Neon API key from environment."""
    api_key = os.getenv("NEON_API_KEY")
    if not api_key:
        raise NeonSetupError(
            "NEON_API_KEY not found in environment.\n"
            "Please add it to Doppler 'local' config.\n"
            "Get your key from: https://console.neon.tech/app/settings/api-keys\n"
            "Use an ORGANIZATION API KEY (not personal) for admin access."
        )
    return api_key


def delete_project(client: httpx.Client, project_name: str, yes: bool = False) -> bool:
    """Delete a Neon project by name. Returns True if deleted, False if not found."""
    # List existing projects
    response = client.get(f"{NEON_API_BASE}/projects")
    response.raise_for_status()
    projects = response.json().get("projects", [])

    # Look for existing project with matching name
    for project in projects:
        if project.get("name") == project_name:
            project_id = project.get("id")
            print(f"\nFound project '{project_name}' (ID: {project_id})")

            if not yes:
                response = input(
                    f"  Delete project '{project_name}' and ALL its data? [type 'DELETE' to confirm] "
                ).strip()
                if response != "DELETE":
                    print("  Deletion cancelled.")
                    return False

            response = client.delete(f"{NEON_API_BASE}/projects/{project_id}")
            response.raise_for_status()
            print(f"[OK] Project deleted: {project_name}")
            return True

    print(f"Project '{project_name}' not found, nothing to delete.")
    return False


def create_compute_endpoint(
    client: httpx.Client,
    project_id: str,
    branch_id: str,
    branch_name: str,
    yes: bool = False,
) -> dict | None:
    """Create a compute endpoint for a branch.

    Uses the Plan autoscaling tier:
    - Min: 0.25 compute (scales to zero after 5 minutes idle)
    - Max: 1 compute
    - Target: 80% CPU before scaling up
    """
    print(f"\n  Creating compute endpoint for branch '{branch_name}'...")

    # If an endpoint already exists for this branch, reuse it.
    endpoints_resp = _request_with_retry(
        client,
        "GET",
        f"{NEON_API_BASE}/projects/{project_id}/endpoints",
    )
    existing_endpoints = endpoints_resp.json().get("endpoints", [])
    for ep in existing_endpoints:
        if ep.get("branch_id") == branch_id and ep.get("type") == "read_write":
            print("  [OK] Existing compute endpoint found")
            print(f"  Endpoint ID: {ep.get('id')}")
            return ep

    if not yes:
        response = input(f"  Create compute endpoint for '{branch_name}'? [Y/n] ").strip().lower()
        if response and response not in ("y", "yes"):
            print("  Compute creation skipped.")
            return None

    response = _request_with_retry(
        client,
        "POST",
        f"{NEON_API_BASE}/projects/{project_id}/endpoints",
        json={
            "endpoint": {
                "branch_id": branch_id,
                "type": "read_write",
                "autoscaling_limit": {
                    "metric": "cpu",
                    "target": 80,
                    "min": "0.25",
                    "max": "1",
                },
            }
        },
    )
    result = response.json()

    endpoint = result.get("endpoint", result)
    print("  [OK] Compute endpoint created")
    print(f"  Endpoint ID: {endpoint.get('id')}")

    # Wait briefly for endpoint to become usable.
    # Neon sometimes reports readiness without populating "connection_parameters",
    # so consider it ready if it has a host and is in an active/ready-like state.
    print("  Waiting for endpoint to be ready...")
    endpoint_id = endpoint.get("id")
    for attempt in range(30):  # Wait up to ~30 seconds
        time.sleep(1)
        check_response = _request_with_retry(
            client,
            "GET",
            f"{NEON_API_BASE}/projects/{project_id}/endpoints/{endpoint_id}",
        )
        updated_endpoint = check_response.json().get("endpoint", check_response.json())

        state = (updated_endpoint.get("state") or updated_endpoint.get("status") or "").lower()
        host = updated_endpoint.get("host") or ""
        has_connection_params = bool(updated_endpoint.get("connection_parameters"))
        ready_state = state in {"active", "idle", "ready", "running"}

        if host and (has_connection_params or ready_state):
            endpoint = updated_endpoint
            print("  Endpoint ready!")
            break

        # Keep logs low-noise.
        if attempt in (4, 9, 19, 29):
            printable_state = state if state else "<unknown>"
            print(f"  Still waiting... ({attempt + 1}s, state={printable_state})")

    return endpoint


def find_or_create_project(client: httpx.Client, project_name: str, yes: bool = False) -> dict:
    """Find existing project or create a new one with PostgreSQL 18 (preview)."""

    # List existing projects (uses the organization associated with the API key)
    print("  Listing existing projects...")
    response = client.get(f"{NEON_API_BASE}/projects")
    response.raise_for_status()
    projects = response.json().get("projects", [])

    # Look for existing project with matching name
    for project in projects:
        if project.get("name") == project_name:
            print(f"[OK] Found existing project: {project_name}")
            print(f"  Project ID: {project['id']}")
            return project

    # Project not found, create new one
    print(f"\nCreating new Neon project: {project_name}")

    if not yes:
        response = (
            input(f"  Create project '{project_name}' with PostgreSQL 18? [Y/n] ").strip().lower()
        )
        if response and response not in ("y", "yes"):
            raise NeonSetupError("Project creation cancelled.")

    response = _request_with_retry(
        client,
        "POST",
        f"{NEON_API_BASE}/projects",
        json={
            "project": {
                "name": project_name,
                "pg_version": 18,
            }
        },
    )
    result = response.json()

    project = result.get("project", result)
    print(f"[OK] Project created: {project_name}")
    print(f"  Project ID: {project.get('id')}")
    print("  PostgreSQL: 18")

    return project


def get_or_create_branch(
    client: httpx.Client,
    project_id: str,
    branch_name: str,
    yes: bool = False,
    create_compute: bool = False,
) -> dict:
    """Get existing branch or create a new one.

    Args:
        create_compute: If True, automatically create compute endpoint for the branch.
    """
    # List existing branches
    response = client.get(f"{NEON_API_BASE}/projects/{project_id}/branches")
    response.raise_for_status()
    branches = response.json().get("branches", [])

    # Look for existing branch
    for branch in branches:
        if branch.get("name") == branch_name or branch.get("id", "").endswith(f"-{branch_name}"):
            print(f"[OK] Found existing branch: {branch_name}")
            branch_id = branch.get("id")

            # Check if branch has endpoints
            if not branch.get("endpoints"):
                if create_compute:
                    # Create compute endpoint automatically
                    endpoint = create_compute_endpoint(
                        client, project_id, branch_id, branch_name, yes
                    )
                    if endpoint:
                        # Update branch with new endpoint
                        branch["endpoints"] = [endpoint]
                else:
                    print(
                        "  Branch has no endpoints. Use --create-compute to add compute automatically."
                    )
                    print("  Or manually add compute via Neon Console:")
                    print("    1. Go to: https://console.neon.tech")
                    print("    2. Select project: fraud-governance")
                    print(f"    3. Select branch: {branch_name}")
                    print(
                        "    4. Click 'Add compute' -> Select 'Plan' (free tier, scales to zero when idle)"
                    )
            return branch

    # Branch not found, create new one
    print(f"\nCreating new branch: {branch_name}")

    if not yes:
        response = input(f"  Create branch '{branch_name}'? [Y/n] ").strip().lower()
        if response and response not in ("y", "yes"):
            raise NeonSetupError(f"Branch '{branch_name}' creation cancelled.")

    response = _request_with_retry(
        client,
        "POST",
        f"{NEON_API_BASE}/projects/{project_id}/branches",
        json={"branch": {"name": branch_name}},
    )
    result = response.json()

    branch = result.get("branch", result)
    branch_id = branch.get("id")
    print(f"[OK] Branch created: {branch_name}")
    print(f"  Branch ID: {branch_id}")

    # Create compute endpoint if requested
    if create_compute:
        endpoint = create_compute_endpoint(client, project_id, branch_id, branch_name, yes)
        if endpoint:
            branch["endpoints"] = [endpoint]
    else:
        # Wait for endpoints to be available (branch provisioning)
        print("  Waiting for endpoints to be ready...")
        for attempt in range(90):  # Wait up to 90 seconds
            time.sleep(1)
            check_response = _request_with_retry(
                client,
                "GET",
                f"{NEON_API_BASE}/projects/{project_id}/branches/{branch_id}",
            )
            updated_branch = check_response.json().get("branch", check_response.json())
            if updated_branch.get("endpoints"):
                branch = updated_branch
                print("  Endpoints ready!")
                break
            if (attempt + 1) % 10 == 0:
                print(f"  Still waiting... ({attempt + 1}s)")

    return branch


def get_connection_info(
    client: httpx.Client,
    project_id: str,
    branch_id: str,
    branch_name: str,
) -> NeonConnectionInfo:
    """Extract connection information using Neon API.

    Uses:
    - GET /projects/{project_id}/endpoints to get host
    - GET /projects/{project_id}/branches/{branch_id}/roles/neondb_owner/reveal_password to get password
    """
    # Get all endpoints
    response = client.get(f"{NEON_API_BASE}/projects/{project_id}/endpoints")
    endpoints = response.json().get("endpoints", [])

    # Find endpoint for this branch
    host = None
    for ep in endpoints:
        if ep.get("branch_id") == branch_id:
            host = ep.get("host")
            break

    if not host:
        return NeonConnectionInfo(
            branch_name=branch_name,
            database_name="neondb",
            host="<ENDPOINT_NOT_READY>",
            owner_password="<ENDPOINT_NOT_READY>",
        )

    # Get owner password via reveal_password API
    response = client.get(
        f"{NEON_API_BASE}/projects/{project_id}/branches/{branch_id}/roles/neondb_owner/reveal_password"
    )
    owner_password = response.json().get("password", "")

    return NeonConnectionInfo(
        branch_name=branch_name,
        database_name="neondb",
        host=host,
        owner_password=owner_password,
    )


def format_connection_strings(
    info: NeonConnectionInfo,
    app_password: str | None = None,
    analytics_password: str | None = None,
    *,
    include_owner_password: bool = False,
) -> dict[str, str]:
    """Format connection strings for Doppler.

    Defaults to printing NO secrets:
    - `DATABASE_URL_ADMIN` uses `{NEON_DB_OWNER_PASSWORD}` placeholder by default.
    - App/analytics passwords default to placeholders too.

    For automation (e.g., syncing Doppler), set `include_owner_password=True`.
    """
    base = "postgresql://"
    ssl = "?sslmode=require"

    app_pass = app_password if app_password else "{FRAUD_GOV_APP_PASSWORD}"
    analytics_pass = analytics_password if analytics_password else "{FRAUD_GOV_ANALYTICS_PASSWORD}"
    owner_pass = info.owner_password if include_owner_password else "{NEON_DB_OWNER_PASSWORD}"

    return {
        "DATABASE_URL_ADMIN": f"{base}neondb_owner:{owner_pass}@{info.host}/{info.database_name}{ssl}",
        "DATABASE_URL_APP": f"{base}fraud_gov_app_user:{app_pass}@{info.host}/{info.database_name}{ssl}",
        "DATABASE_URL_ANALYTICS": f"{base}fraud_gov_analytics_user:{analytics_pass}@{info.host}/{info.database_name}{ssl}",
    }


def print_connection_info(
    branch_info: str, connection_strings: dict[str, str], with_placeholders: bool = True
) -> None:
    """Print connection information for a branch."""
    print()
    print("=" * 78)
    print(branch_info)
    print("=" * 78)
    print()

    if with_placeholders:
        print(
            "IMPORTANT: Replace placeholders with passwords from THAT environment's Doppler config:"
        )
        print(
            "  - {NEON_DB_OWNER_PASSWORD} -> Neon branch owner password (use automation, do NOT paste into docs)"
        )
        print("  - {FRAUD_GOV_APP_PASSWORD} -> Get from Doppler test/prod config")
        print("  - {FRAUD_GOV_ANALYTICS_PASSWORD} -> Get from Doppler test/prod config")
        print()
        print("Example Doppler commands:")
        print(
            "  doppler secrets --project=card-fraud-rule-management --config=test get FRAUD_GOV_APP_PASSWORD --raw"
        )
        print(
            '  doppler secrets --project=card-fraud-rule-management --config=test set DATABASE_URL_APP "<url_with_real_password>"'
        )
        print()
        print("Copy these to Doppler (REPLACE placeholders with actual passwords):")
        print()
    else:
        print("Copy these to Doppler:")
        print()

    for key, value in connection_strings.items():
        print(f"{key}={value}")
    print()


def verify_connection(connection_string: str) -> bool:
    """Verify that a connection string works."""
    try:
        # Parse connection string to get host/database
        # For now, just verify the format is correct
        if "postgresql://" in connection_string and "@" in connection_string:
            return True
        return False
    except Exception:
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Set up Neon project and branches for fraud-rule-management"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--delete-project",
        action="store_true",
        help="Delete the existing Neon project and exit (use with --yes to skip confirmation)",
    )
    parser.add_argument(
        "--create-compute",
        action="store_true",
        help="Automatically create compute endpoints for branches (Plan autoscaling tier)",
    )
    parser.add_argument(
        "--project-name",
        default=PROJECT_NAME,
        help=f"Neon project name (default: {PROJECT_NAME})",
    )
    args = parser.parse_args()

    try:
        # Get API key
        api_key = get_neon_api_key()
        print("[OK] Neon API key found")

        # Create HTTP client
        client = httpx.Client(
            base_url=NEON_API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        # Handle delete-project mode
        if args.delete_project:
            print()
            print("=" * 78)
            print("DELETE NEON PROJECT")
            print("=" * 78)
            print()

            deleted = delete_project(client, args.project_name, args.yes)
            if deleted:
                print()
                print(
                    "Project deleted successfully. Run again without --delete-project to create a new one."
                )
            return 0

        print()
        print("=" * 78)
        print("NEON DATABASE SETUP")
        print("=" * 78)
        if args.create_compute:
            print("Compute creation: ENABLED (Plan autoscaling tier)")
        else:
            print("Compute creation: DISABLED (use --create-compute to enable)")
        print("=" * 78)
        print()

        # Find or create project
        project = find_or_create_project(client, args.project_name, args.yes)
        project_id = project["id"]

        # Setup test branch
        print()
        print("-" * 78)
        print("Setting up TEST branch...")
        print("-" * 78)
        test_branch = get_or_create_branch(
            client, project_id, "test", args.yes, args.create_compute
        )
        test_info = get_connection_info(client, project_id, test_branch["id"], "test")

        # Always use placeholders for test/prod (passwords come from each Doppler config)
        test_connection_strings = format_connection_strings(
            test_info
        )  # No passwords = placeholders
        print_connection_info(
            "TEST BRANCH - Copy to Doppler 'test' config:",
            test_connection_strings,
            with_placeholders=True,
        )

        # Setup prod branch
        print()
        print("-" * 78)
        print("Setting up PROD branch...")
        print("-" * 78)
        prod_branch = get_or_create_branch(
            client, project_id, "prod", args.yes, args.create_compute
        )
        prod_info = get_connection_info(client, project_id, prod_branch["id"], "prod")

        # Always use placeholders for test/prod (passwords come from each Doppler config)
        prod_connection_strings = format_connection_strings(
            prod_info
        )  # No passwords = placeholders
        print_connection_info(
            "PROD BRANCH - Copy to Doppler 'prod' config:",
            prod_connection_strings,
            with_placeholders=True,
        )

        # Summary
        print()
        print("=" * 78)
        print("SETUP COMPLETE")
        print("=" * 78)
        print()
        print("Next steps:")
        print()
        print("1. Sync Doppler DATABASE_URL_* for test/prod (secure; does not print passwords):")
        print("   uv run db-sync-doppler-urls --yes")
        print()
        print("2. Initialize test database:")
        print("   uv run db-init-test")
        print()
        print("3. Initialize prod database:")
        print("   uv run db-init-prod")
        print()
        print("=" * 78)

        return 0

    except NeonSetupError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as e:
        print(f"\nNeon API error: {e.response.status_code}", file=sys.stderr)
        try:
            error_data = e.response.json()
            print(f"  {error_data}", file=sys.stderr)
        except Exception:
            print(f"  {e.response.text}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return 130
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
