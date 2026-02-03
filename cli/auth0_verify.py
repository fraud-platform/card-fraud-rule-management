"""CLI wrapper for Auth0 verification with Doppler."""

import subprocess
import sys

DOPPLER_PROJECT = "card-fraud-rule-management"


def main():
    """Run Auth0 verification with Doppler secrets."""
    cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        "local",
        "--",
        sys.executable,
        "scripts/verify_auth0.py",
    ]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
