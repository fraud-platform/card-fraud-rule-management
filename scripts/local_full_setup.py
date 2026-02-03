#!/usr/bin/env python3
"""Full local database setup automation.

This script performs a complete local Docker PostgreSQL setup:
1. Starts Docker PostgreSQL 18 (if not running)
2. Waits for database to be ready
3. Runs db-init (DDL, indexes, seed data)
4. Verifies database setup

Usage:
    uv run local-full-setup --yes

    # Reset and reinitialize
    uv run local-full-setup --reset --yes

Requirements:
    - Docker Desktop running
    - Doppler configured with 'local' config
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

DOPPLER_PROJECT = "card-fraud-rule-management"


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


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(cmd, text=True, capture_output=True)
    if check and result.returncode != 0:
        log_error(f"Command failed: {' '.join(cmd)}")
        if result.stdout:
            print(f"stdout: {result.stdout}")
        if result.stderr:
            print(f"stderr: {result.stderr}")
    return result


def is_docker_running() -> bool:
    """Check if Docker is running."""
    result = run_command(["docker", "info"], check=False)
    return result.returncode == 0


def is_postgres_container_running() -> bool:
    """Check if the local Postgres container is running."""
    result = run_command(
        ["docker", "ps", "--filter", "name=fraud-gov-postgres", "--format", "{{.Names}}"],
        check=False,
    )
    return "fraud-gov-postgres" in result.stdout


def start_postgres_container() -> bool:
    """Start the local Postgres container using db-local-up."""
    log_info("Starting Docker PostgreSQL 18...")

    # Use the CLI command which handles Doppler integration
    result = subprocess.run(
        ["uv", "run", "db-local-up"],
        text=True,
    )
    return result.returncode == 0


def stop_postgres_container() -> bool:
    """Stop the local Postgres container."""
    log_info("Stopping Docker PostgreSQL...")
    result = subprocess.run(["uv", "run", "db-local-down"], text=True)
    return result.returncode == 0


def reset_postgres_container() -> bool:
    """Reset the local Postgres container (delete volume)."""
    log_info("Resetting Docker PostgreSQL (deleting volume)...")
    result = subprocess.run(["uv", "run", "db-local-reset"], text=True)
    return result.returncode == 0


def wait_for_postgres(max_attempts: int = 30, sleep_seconds: float = 2.0) -> bool:
    """Wait for PostgreSQL to be ready to accept connections."""
    log_info("Waiting for PostgreSQL to be ready...")

    for attempt in range(1, max_attempts + 1):
        # Try to connect using psql via docker exec
        result = run_command(
            [
                "docker",
                "exec",
                "fraud-gov-postgres",
                "pg_isready",
                "-U",
                "postgres",
                "-d",
                "fraud_gov",
            ],
            check=False,
        )

        if result.returncode == 0:
            log_success("PostgreSQL is ready!")
            return True

        if attempt % 5 == 0:
            log_info(f"Still waiting... ({attempt}/{max_attempts})")

        time.sleep(sleep_seconds)

    log_error("PostgreSQL did not become ready in time")
    return False


def run_db_init() -> bool:
    """Run db-init-local to initialize the database."""
    log_info("Initializing database (schema, users, indexes, seed data)...")

    scripts_dir = Path(__file__).parent
    setup_script = scripts_dir / "setup_database.py"

    cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        "local",
        "--",
        sys.executable,
        str(setup_script),
        "--password-env",
        "--yes",
        "init",
    ]

    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        log_error("db-init failed")
        return False

    log_success("Database initialized successfully")
    return True


def run_db_verify() -> bool:
    """Run db-verify-local to verify the database."""
    log_info("Verifying database setup...")

    scripts_dir = Path(__file__).parent
    setup_script = scripts_dir / "setup_database.py"

    cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        "local",
        "--",
        sys.executable,
        str(setup_script),
        "verify",
    ]

    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        log_error("db-verify failed")
        return False

    log_success("Database verified successfully")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full local database setup automation")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset database (delete Docker volume) before setup",
    )
    args = parser.parse_args(argv)

    if not args.yes:
        print("This will set up the local Docker PostgreSQL database. Use --yes to confirm.")
        return 2

    total_steps = 5 if args.reset else 4
    step = 1

    try:
        # Step 1: Check Docker
        log_step(step, total_steps, "Checking Docker...")
        if not is_docker_running():
            log_error("Docker is not running. Please start Docker Desktop.")
            return 1
        log_success("Docker is running")
        step += 1

        # Step 2: Reset if requested
        if args.reset:
            log_step(step, total_steps, "Resetting database...")
            if is_postgres_container_running():
                stop_postgres_container()
            reset_postgres_container()
            step += 1

        # Step 3: Start PostgreSQL
        log_step(step, total_steps, "Starting PostgreSQL container...")
        if is_postgres_container_running():
            log_info("PostgreSQL container already running")
        else:
            if not start_postgres_container():
                log_error("Failed to start PostgreSQL container")
                return 1
        step += 1

        # Step 4: Wait for PostgreSQL
        log_step(step, total_steps, "Waiting for PostgreSQL to be ready...")
        if not wait_for_postgres():
            return 1
        step += 1

        # Step 5: Initialize database
        log_step(step, total_steps, "Initializing and verifying database...")
        if not run_db_init():
            return 1
        if not run_db_verify():
            return 1

        # Summary
        print()
        print("=" * 70)
        print(f"{Colors.GREEN}{Colors.BOLD}LOCAL DATABASE SETUP COMPLETE{Colors.END}")
        print("=" * 70)
        print()
        print("Database ready at: postgresql://localhost:5432/fraud_gov")
        print()
        print("Next steps:")
        print("  - Start dev server: uv run doppler-local")
        print("  - Run local tests:  uv run doppler-local-test")
        print()

        return 0

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
