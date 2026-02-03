"""Auth0 cleanup wrapper (Doppler + uv-friendly).

Usage:
    uv run auth0-cleanup --yes --verbose
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DOPPLER_PROJECT = "card-fraud-rule-management"
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_CLEANUP_SCRIPT = _SCRIPTS_DIR / "cleanup_auth0.py"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up Auth0 resources (preserves Management M2M app)"
    )
    parser.add_argument(
        "--config",
        default="local",
        help="Doppler config to use (default: local)",
    )
    parser.add_argument(
        "--no-doppler",
        action="store_true",
        help="Run without Doppler (expects env vars already set)",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details")
    args = parser.parse_args()

    script_args: list[str] = []
    if args.yes:
        script_args.append("--yes")
    if args.verbose:
        script_args.append("--verbose")

    cmd = [sys.executable, str(_CLEANUP_SCRIPT), *script_args]

    if args.no_doppler:
        sys.exit(subprocess.run(cmd, check=False).returncode)

    full_cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        args.config,
        "--",
    ] + cmd

    sys.exit(subprocess.run(full_cmd, check=False).returncode)


if __name__ == "__main__":
    main()
