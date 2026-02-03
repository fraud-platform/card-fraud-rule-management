"""
Local database management commands.

Start/stop local PostgreSQL for development and testing.
Checks for shared platform infrastructure first (card-fraud-platform),
falls back to local docker-compose if not available.

Usage:
    uv run db-local-up      # Start local Postgres (with Doppler)
    uv run db-local-down    # Stop local Postgres
    uv run db-local-reset   # Reset (delete all data and restart)
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

# Doppler project configuration
DOPPLER_PROJECT = "card-fraud-rule-management"
DOPPLER_CONFIG = "local"

# Container name (matches shared platform)
POSTGRES_CONTAINER = "card-fraud-postgres"


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=False)


def _is_platform_container_running() -> bool:
    """Check if the shared platform PostgreSQL container is already running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", POSTGRES_CONTAINER],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "running"


def _docker_compose_cmd(args: list[str]) -> list[str]:
    """Build docker-compose command wrapped in Doppler for env vars."""
    project_root = _get_project_root()
    compose_file = project_root / "docker-compose.local.yml"

    if not compose_file.exists():
        print("ERROR: docker-compose.local.yml not found")
        sys.exit(1)

    # Wrap docker compose with doppler run to inject environment variables
    return [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        DOPPLER_CONFIG,
        "--",
        "docker",
        "compose",
        "-f",
        str(compose_file),
    ] + args


def up() -> None:
    """Start local PostgreSQL database with Doppler environment variables."""
    if _is_platform_container_running():
        print(f"[OK] PostgreSQL already running via shared platform ({POSTGRES_CONTAINER})")
        print("     Managed by: card-fraud-platform")
        print("     Endpoint: postgresql://localhost:5432/fraud_gov")
        return

    print("Starting local PostgreSQL with Doppler secrets...")
    cmd = _docker_compose_cmd(["up", "-d"])
    _run(cmd)

    print("Waiting for database to be ready...")
    for _i in range(30):
        result = subprocess.run(
            ["docker", "exec", POSTGRES_CONTAINER, "pg_isready", "-U", "postgres"],
            capture_output=True,
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        print("ERROR: Database failed to start")
        sys.exit(1)

    print()
    print("=" * 70)
    print("Local PostgreSQL is ready!")
    print("=" * 70)
    print()
    print("Connection strings:")
    print("  DATABASE_URL_ADMIN=postgresql://postgres:<password>@localhost:5432/fraud_gov")
    print(
        "  DATABASE_URL_APP=postgresql://fraud_gov_app_user:localdevpass@localhost:5432/fraud_gov"
    )
    print(
        "  DATABASE_URL_ANALYTICS=postgresql://fraud_gov_analytics_user:localdevpass@localhost:5432/fraud_gov"
    )
    print()
    print("If you haven't added DATABASE_URL_* to Doppler yet, run:")
    print("  doppler run --config local -- uv run python scripts/generate_local_urls.py")
    print()
    print("Then start the API:")
    print("  uv run doppler-local")
    print()


def down() -> None:
    """Stop local PostgreSQL database."""
    if _is_platform_container_running():
        print(f"[INFO] PostgreSQL is managed by card-fraud-platform ({POSTGRES_CONTAINER})")
        print("       To stop: cd ../card-fraud-platform && uv run platform-down")
        return

    print("Stopping local PostgreSQL...")
    cmd = _docker_compose_cmd(["down"])
    _run(cmd)
    print("Done.")


def reset() -> None:
    """Reset local database (delete all data and restart)."""
    print("Resetting local PostgreSQL (all data will be deleted)...")
    cmd = _docker_compose_cmd(["down", "-v"])
    _run(cmd)

    print("Starting fresh database...")
    up()


def infra_up() -> None:
    """Start all local infrastructure (PostgreSQL + MinIO)."""
    if _is_platform_container_running():
        print("[OK] Infrastructure already running via shared platform")
        print("     Managed by: card-fraud-platform")
        return

    from cli.objstore_local import infra_up as _infra_up

    _infra_up()
