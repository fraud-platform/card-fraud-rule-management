#!/usr/bin/env python3
"""Sync Doppler DATABASE_URL_* secrets from Neon endpoints.

Goal
- Fully automate updating Doppler `DATABASE_URL_ADMIN`, `DATABASE_URL_APP`, `DATABASE_URL_ANALYTICS`
  for the `test` and `prod` configs based on the current Neon endpoint hosts.

Security
- Does NOT print secrets or full connection strings by default.
- Prints only hostnames and which keys were updated.
- Use `--verbose` to print redacted URLs (passwords masked).

Expected environment
- Run via `uv run db-sync-doppler-urls --yes` so Doppler `local` config injects NEON_API_KEY.
- Requires Doppler CLI access (for reading/writing secrets).

This script intentionally uses the Doppler CLI (not Doppler API) to keep auth flow consistent
with how developers already access secrets.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.setup_neon import (
    NeonSetupError,
    find_or_create_project,
    format_connection_strings,
    get_connection_info,
    get_neon_api_key,
    get_or_create_branch,
    httpx,
)

DOPPLER_PROJECT = "card-fraud-rule-management"


class DopplerError(RuntimeError):
    pass


@dataclass(frozen=True)
class DopplerConfigUpdate:
    doppler_config: str
    neon_branch: str
    neon_branch_label: str


UPDATES: list[DopplerConfigUpdate] = [
    DopplerConfigUpdate(doppler_config="test", neon_branch="test", neon_branch_label="test"),
    DopplerConfigUpdate(doppler_config="prod", neon_branch="prod", neon_branch_label="prod"),
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def _doppler_get(config: str, name: str) -> str:
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
        ]
    )
    if proc.returncode != 0:
        raise DopplerError(
            proc.stderr.strip() or f"Failed to read Doppler secret '{name}' from config '{config}'."
        )
    return proc.stdout.strip()


def _doppler_set(config: str, name: str, value: str) -> None:
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
        ]
    )
    if proc.returncode != 0:
        raise DopplerError(
            proc.stderr.strip() or f"Failed to set Doppler secret '{name}' in config '{config}'."
        )


def _mask_password(url: str) -> str:
    # Very small helper to hide credentials in a postgresql://user:pass@host/... string.
    if "postgresql://" not in url or "@" not in url:
        return url

    prefix, rest = url.split("postgresql://", 1)
    creds, after_at = rest.split("@", 1)
    if ":" not in creds:
        return url

    user, _pw = creds.split(":", 1)
    return f"postgresql://{user}:******@{after_at}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Doppler DATABASE_URL_* from Neon endpoints")
    parser.add_argument("--yes", "-y", action="store_true", help="Apply changes without prompting")
    parser.add_argument(
        "--create-compute",
        action="store_true",
        help="Ensure compute endpoints exist (may create endpoints if missing)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print redacted URLs (passwords masked) for troubleshooting",
    )
    args = parser.parse_args(argv)

    if not args.yes:
        print("Refusing to modify Doppler without --yes.", file=sys.stderr)
        return 2

    # Make sure we have access to Neon API key.
    _ = get_neon_api_key()

    try:
        client = httpx.Client(
            base_url="https://console.neon.tech/api/v2",
            headers={"Authorization": f"Bearer {os.environ['NEON_API_KEY']}"},
            timeout=30.0,
        )

        project = find_or_create_project(client, "fraud-governance", yes=True)
        project_id = project["id"]

        for update in UPDATES:
            branch = get_or_create_branch(
                client,
                project_id,
                update.neon_branch,
                yes=True,
                create_compute=args.create_compute,
            )
            info = get_connection_info(client, project_id, branch["id"], update.neon_branch_label)
            if "<ENDPOINT_NOT_READY>" in info.host:
                raise NeonSetupError(
                    f"Neon endpoint for branch '{update.neon_branch}' is not ready. "
                    "Re-run with --create-compute or create compute via Neon Console."
                )

            app_password = _doppler_get(update.doppler_config, "FRAUD_GOV_APP_PASSWORD")
            analytics_password = _doppler_get(update.doppler_config, "FRAUD_GOV_ANALYTICS_PASSWORD")

            urls = format_connection_strings(
                info,
                app_password=app_password,
                analytics_password=analytics_password,
                include_owner_password=True,
            )

            # Apply updates (no printing of secrets).
            _doppler_set(update.doppler_config, "DATABASE_URL_ADMIN", urls["DATABASE_URL_ADMIN"])
            _doppler_set(update.doppler_config, "DATABASE_URL_APP", urls["DATABASE_URL_APP"])
            _doppler_set(
                update.doppler_config, "DATABASE_URL_ANALYTICS", urls["DATABASE_URL_ANALYTICS"]
            )

            print(
                f"[OK] Updated Doppler '{update.doppler_config}' DATABASE_URL_* (host={info.host})"
            )
            if args.verbose:
                print(f"  DATABASE_URL_ADMIN={_mask_password(urls['DATABASE_URL_ADMIN'])}")
                print(f"  DATABASE_URL_APP={_mask_password(urls['DATABASE_URL_APP'])}")
                print(f"  DATABASE_URL_ANALYTICS={_mask_password(urls['DATABASE_URL_ANALYTICS'])}")

        return 0

    except (NeonSetupError, DopplerError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
