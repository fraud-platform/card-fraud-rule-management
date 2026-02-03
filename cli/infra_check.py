"""
Unified infrastructure management for rule-mgmt.

Checks for shared platform infrastructure first (card-fraud-platform),
provides options to start platform or fall back to local infrastructure.

Usage:
    uv run infra-check           # Check infrastructure status
    uv run infra-local-up        # Start local fallback infra (PostgreSQL + MinIO)
    uv run infra-local-down      # Stop local fallback infra

Platform Infrastructure (card-fraud-platform):
    - card-fraud-postgres     (PostgreSQL 18)
    - card-fraud-minio        (MinIO S3-compatible storage)
    - card-fraud-redis        (Redis 8.4)
    - card-fraud-redpanda     (Kafka-compatible streaming)
    - card-fraud-redpanda-console  (Redpanda web UI)

This project needs:
    - PostgreSQL (for database)
    - MinIO (for ruleset artifact storage)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# All platform infrastructure containers
PLATFORM_INFRA = [
    ("card-fraud-postgres", "PostgreSQL 18", "localhost:5432", "fraud_gov database"),
    ("card-fraud-minio", "MinIO S3", "localhost:9000", "S3-compatible storage"),
    ("card-fraud-redis", "Redis 8.4", "localhost:6379", "Cache/velocity"),
    ("card-fraud-redpanda", "Redpanda", "localhost:9092", "Kafka-compatible"),
    ("card-fraud-redpanda-console", "Redpanda Console", "localhost:8083", "Web UI"),
]

# Required by this project
REQUIRED_FOR_RULE_MGMT = [
    ("card-fraud-postgres", "PostgreSQL", "localhost:5432"),
    ("card-fraud-minio", "MinIO", "localhost:9000"),
]

# Platform project path
PLATFORM_PATH = Path(__file__).parent.parent.parent / "card-fraud-platform"


def _is_container_running(name: str) -> bool:
    """Check if a container is running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "running"


def _is_platform_available() -> bool:
    """Check if card-fraud-platform project exists locally."""
    return PLATFORM_PATH.exists() and (PLATFORM_PATH / "docker-compose.yml").exists()


def _get_container_status() -> dict[str, dict]:
    """Get status of all platform infrastructure containers."""
    status = {}
    for name, display, endpoint, description in PLATFORM_INFRA:
        running = _is_container_running(name)
        status[name] = {
            "running": running,
            "display": display,
            "endpoint": endpoint,
            "description": description,
        }
    return status


def _print_status(status: dict[str, dict]) -> None:
    """Print infrastructure status table."""
    print()
    print("=" * 80)
    print(f"  {'Container':<30} {'Status':<12} {'Endpoint':<20}")
    print("-" * 80)
    for name, info in status.items():
        icon = "[RUNNING]" if info["running"] else "[STOPPED]"
        print(f"  {icon} {name:<24} {info['display']:<12} {info['endpoint']:<20}")
    print("=" * 80)


def _print_rule_mgmt_status(status: dict[str, dict]) -> None:
    """Print rule-mgmt specific infrastructure status."""
    print()
    print("Required for card-fraud-rule-management:")
    print("-" * 60)

    all_required_running = True
    for name, display, endpoint in REQUIRED_FOR_RULE_MGMT:
        info = status.get(name, {})
        running = info.get("running", False)
        icon = "[OK]" if running else "[MISSING]"
        state = "running" if running else "NOT RUNNING"
        print(f"  {icon} {name:<20} {display:<15} {endpoint:<20} {state}")
        if not running:
            all_required_running = False

    print("-" * 60)
    if all_required_running:
        print("Status: All required infrastructure is RUNNING")
    else:
        print("Status: Some required infrastructure is MISSING")
    print()


def check() -> None:
    """Check infrastructure status and show recommendations."""
    print("Card Fraud Rule Management - Infrastructure Check")
    print()

    status = _get_container_status()
    _print_status(status)
    _print_rule_mgmt_status(status)

    # Count running containers
    running_count = sum(1 for v in status.values() if v["running"])
    required_running = sum(
        1 for name, _, _ in REQUIRED_FOR_RULE_MGMT
        if status.get(name, {}).get("running", False)
    )

    print()
    print("Recommendations:")
    print()

    # Check if platform is available
    platform_available = _is_platform_available()

    if running_count == len(PLATFORM_INFRA):
        print("  [OK] All platform infrastructure is running")
        print("       Managed by: card-fraud-platform")
        print()
        print("  To stop: cd ../card-fraud-platform && uv run platform-down")
    elif required_running == len(REQUIRED_FOR_RULE_MGMT):
        print("  [OK] Required infrastructure for rule-mgmt is running")
        if platform_available:
            print()
            print("  [INFO] Platform project detected but not all containers running")
            print("        To start full platform:")
            print(f"          cd {PLATFORM_PATH}")
            print("          uv run platform-up")
    else:
        print("  [ACTION] Infrastructure needs to be started")
        print()
        if platform_available:
            print("  Option 1: Start platform infrastructure (recommended):")
            print(f"            cd {PLATFORM_PATH}")
            print("            uv run platform-up")
            print()
            print("  Option 2: Start local fallback infrastructure:")
            print("            uv run infra-local-up")
        else:
            print("  Start local fallback infrastructure:")
            print("    uv run infra-local-up")


def main() -> int:
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check()
        return 0

    # Default: show status
    check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
