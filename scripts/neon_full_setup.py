#!/usr/bin/env python3
"""Full Neon database setup automation.

This script performs a complete Neon project setup:
1. Deletes existing Neon project (if exists)
2. Creates new project with 'test' and 'prod' branches
3. Creates compute endpoints for each branch
4. Syncs DATABASE_URL_* to Doppler test/prod configs
5. Runs db-init (DDL, indexes, seed data) for test and prod
6. Verifies database setup

Usage:
    uv run neon-full-setup --yes

    # With specific config (test or prod only)
    uv run neon-full-setup --config=test --yes
    uv run neon-full-setup --config=prod --yes

Requirements:
    - NEON_API_KEY in environment (from Doppler 'local' config)
    - Doppler CLI configured for project 'card-fraud-rule-management'
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from scripts.setup_neon import (
    NEON_API_BASE,
    NeonSetupError,
    delete_project,
    find_or_create_project,
    format_connection_strings,
    get_connection_info,
    get_neon_api_key,
    get_or_create_branch,
)

DOPPLER_PROJECT = "card-fraud-rule-management"
PROJECT_NAME = "fraud-governance"


class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def log_step(step: int, total: int, msg: str) -> None:
    print(f"\n{Colors.BOLD}[{step}/{total}] {msg}{Colors.END}")


def log_info(msg: str) -> None:
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")


def log_success(msg: str) -> None:
    print(f"{Colors.GREEN}[OK]{Colors.END} {msg}")


def log_error(msg: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.END} {msg}")


def log_warning(msg: str) -> None:
    print(f"{Colors.YELLOW}[WARN]{Colors.END} {msg}")


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command."""
    result = subprocess.run(cmd, text=True, capture_output=True)
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
    return result


def _doppler_get(config: str, name: str) -> str:
    """Get a secret from Doppler."""
    proc = _run(
        [
            "doppler",
            "secrets",
            "--project",
            DOPPLER_PROJECT,
            "--config",
            config,
            "get",
            name,
            "--plain",
        ],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to read Doppler secret '{name}' from config '{config}'")
    return proc.stdout.strip()


def _doppler_set(config: str, name: str, value: str) -> None:
    """Set a secret in Doppler."""
    proc = _run(
        [
            "doppler",
            "secrets",
            "--project",
            DOPPLER_PROJECT,
            "--config",
            config,
            "set",
            name,
            value,
        ],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to set Doppler secret '{name}' in config '{config}'")


def sync_doppler_urls(
    client: httpx.Client,
    project_id: str,
    branch_id: str,
    branch_name: str,
    doppler_config: str,
) -> None:
    """Sync DATABASE_URL_* to a Doppler config."""
    log_info(f"Syncing Doppler '{doppler_config}' config...")

    info = get_connection_info(client, project_id, branch_id, branch_name)
    if "<ENDPOINT_NOT_READY>" in info.host:
        raise NeonSetupError(f"Neon endpoint for branch '{branch_name}' is not ready")

    app_password = _doppler_get(doppler_config, "FRAUD_GOV_APP_PASSWORD")
    analytics_password = _doppler_get(doppler_config, "FRAUD_GOV_ANALYTICS_PASSWORD")

    urls = format_connection_strings(
        info,
        app_password=app_password,
        analytics_password=analytics_password,
        include_owner_password=True,
    )

    _doppler_set(doppler_config, "DATABASE_URL_ADMIN", urls["DATABASE_URL_ADMIN"])
    _doppler_set(doppler_config, "DATABASE_URL_APP", urls["DATABASE_URL_APP"])
    _doppler_set(doppler_config, "DATABASE_URL_ANALYTICS", urls["DATABASE_URL_ANALYTICS"])

    log_success(f"Updated Doppler '{doppler_config}' DATABASE_URL_* (host={info.host})")


def run_db_init(config: str) -> bool:
    """Run db-init for a specific config."""
    log_info(f"Running db-init for '{config}'...")

    # Get the setup_database.py path
    scripts_dir = Path(__file__).parent
    setup_script = scripts_dir / "setup_database.py"

    cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        config,
        "--",
        sys.executable,
        str(setup_script),
        "--password-env",
        "--yes",
        "init",
    ]

    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        log_error(f"db-init failed for '{config}'")
        return False

    log_success(f"db-init completed for '{config}'")
    return True


def run_db_verify(config: str) -> bool:
    """Run db-verify for a specific config."""
    log_info(f"Verifying database for '{config}'...")

    scripts_dir = Path(__file__).parent
    setup_script = scripts_dir / "setup_database.py"

    cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        config,
        "--",
        sys.executable,
        str(setup_script),
        "verify",
    ]

    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        log_error(f"db-verify failed for '{config}'")
        return False

    log_success(f"db-verify completed for '{config}'")
    return True


def setup_single_config(
    client: httpx.Client,
    project_id: str,
    config: str,
) -> bool:
    """Setup a single Neon branch and sync to Doppler."""
    branch_name = config  # 'test' or 'prod'

    log_info(f"Setting up '{branch_name}' branch...")
    branch = get_or_create_branch(client, project_id, branch_name, yes=True, create_compute=True)
    branch_id = branch["id"]

    # Sync to Doppler
    sync_doppler_urls(client, project_id, branch_id, branch_name, config)

    # Run db-init
    if not run_db_init(config):
        return False

    # Verify
    if not run_db_verify(config):
        return False

    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full Neon database setup automation")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument(
        "--config",
        choices=["test", "prod"],
        help="Setup only a specific config (default: both test and prod)",
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Skip deleting existing project (use for incremental setup)",
    )
    parser.add_argument(
        "--project-name",
        default=PROJECT_NAME,
        help=f"Neon project name (default: {PROJECT_NAME})",
    )
    args = parser.parse_args(argv)

    if not args.yes:
        print("This will DELETE and RECREATE the Neon project. Use --yes to confirm.")
        return 2

    configs_to_setup = [args.config] if args.config else ["test", "prod"]
    total_steps = (
        2 + len(configs_to_setup) * 3
    )  # delete + create + (sync + init + verify) per config

    try:
        # Step 1: Get API key and create client
        api_key = get_neon_api_key()
        log_success("Neon API key found")

        client = httpx.Client(
            base_url=NEON_API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        step = 1

        # Step 2: Delete existing project
        if not args.skip_delete:
            log_step(step, total_steps, "Deleting existing Neon project...")
            delete_project(client, args.project_name, yes=True)
            step += 1

            # Brief pause after deletion
            log_info("Waiting for cleanup...")
            time.sleep(2)

        # Step 3: Create project
        log_step(step, total_steps, "Creating Neon project...")
        project = find_or_create_project(client, args.project_name, yes=True)
        project_id = project["id"]
        step += 1

        # Setup each config
        for config in configs_to_setup:
            log_step(step, total_steps, f"Setting up '{config}' branch and endpoint...")

            branch_name = config
            branch = get_or_create_branch(
                client, project_id, branch_name, yes=True, create_compute=True
            )
            branch_id = branch["id"]
            step += 1

            log_step(step, total_steps, f"Syncing Doppler '{config}' and initializing database...")
            sync_doppler_urls(client, project_id, branch_id, branch_name, config)

            if not run_db_init(config):
                return 1
            step += 1

            log_step(step, total_steps, f"Verifying '{config}' database...")
            if not run_db_verify(config):
                return 1
            step += 1

        # Summary
        print()
        print("=" * 70)
        print(f"{Colors.GREEN}{Colors.BOLD}FULL NEON SETUP COMPLETE{Colors.END}")
        print("=" * 70)
        print()
        print("Configured environments:")
        for config in configs_to_setup:
            print(f"  - Doppler '{config}' -> Neon branch '{config}'")
        print()
        print("Next steps:")
        print("  - Run tests: uv run doppler-test")
        if "prod" in configs_to_setup:
            print("  - Run prod tests: uv run doppler-prod")
        print()

        return 0

    except NeonSetupError as e:
        log_error(str(e))
        return 1
    except httpx.HTTPStatusError as e:
        log_error(f"Neon API error: {e.response.status_code}")
        try:
            print(f"  {e.response.json()}")
        except Exception:
            print(f"  {e.response.text}")
        return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return 130
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
