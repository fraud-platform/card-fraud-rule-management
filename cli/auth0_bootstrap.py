"""Auth0 bootstrap wrapper (Doppler + uv-friendly).

Provides a single command for onboarding (humans and agents):

    uv run auth0-bootstrap --yes --verbose

By default, runs under Doppler `local` config to inject secrets.

This wrapper intentionally:
- Restricts passthrough args (only --yes/-y and --verbose)
- Avoids printing secrets
- Is safe to re-run because scripts/setup_auth0.py is idempotent
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DOPPLER_PROJECT = "card-fraud-rule-management"

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_SETUP_AUTH0_SCRIPT = _SCRIPTS_DIR / "setup_auth0.py"


def _validate_doppler_config(value: str) -> str:
    config = value.strip().lower()
    allowed = {"local", "test", "prod"}
    if config not in allowed:
        allowed_display = ", ".join(sorted(allowed))
        raise SystemExit(f"Unsupported --config '{value}'. Allowed: {allowed_display}")
    return config


def _run_doppler(config: str, cmd: list[str]) -> int:
    full_cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        config,
        "--",
    ] + cmd
    return subprocess.run(full_cmd, check=False).returncode  # nosec


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap Auth0 tenant objects (idempotent). Defaults to Doppler 'local' config."
        )
    )
    parser.add_argument(
        "--config",
        default="local",
        help="Doppler config to use (default: local).",
    )
    parser.add_argument(
        "--no-doppler",
        action="store_true",
        help="Run without Doppler (expects env vars already set).",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Run without prompting")
    parser.add_argument("--verbose", action="store_true", help="Print created/updated object IDs")
    parser.add_argument(
        "--skip-test-users",
        action="store_true",
        help="Skip test user creation (useful if you want to manage test users separately)",
    )
    args, unknown = parser.parse_known_args()

    if unknown:
        raise SystemExit(
            "Unsupported extra arguments: "
            + " ".join(unknown)
            + "\nOnly --yes/-y, --verbose, and --skip-test-users are forwarded."
        )

    script_args: list[str] = []
    if args.yes:
        script_args.append("--yes")
    if args.verbose:
        script_args.append("--verbose")
    if args.skip_test_users:
        script_args.append("--skip-test-users")

    cmd = [sys.executable, str(_SETUP_AUTH0_SCRIPT), *script_args]

    if args.no_doppler:
        sys.exit(subprocess.run(cmd, check=False).returncode)  # nosec

    # Ensure dotenv files do not override Doppler-provided secrets.
    # This mirrors the behavior of cli/doppler_local.py.
    import os

    os.environ["ENV_FILE"] = ""

    sys.exit(_run_doppler(_validate_doppler_config(args.config), cmd))
