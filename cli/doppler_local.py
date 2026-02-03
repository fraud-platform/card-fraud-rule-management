"""
Doppler development commands.

Run development commands with Doppler secrets injected.

Usage:
    uv run doppler-local       # Run dev server with Doppler (local config)
    uv run doppler-local-test  # Run tests with Doppler (local config - local Docker)
    uv run doppler-test-local  # (compat) Same as doppler-local-test
    uv run doppler-test        # Run tests with Doppler (test config - Neon)
    uv run doppler-prod        # Run tests with Doppler (prod config - Neon production)
"""

from __future__ import annotations

import sys

from cli._runner import run

_DOPPLER_PROJECT_FLAG = "--project=card-fraud-rule-management"


def _doppler_run_prefix(config: str) -> list[str]:
    return [
        "doppler",
        "run",
        _DOPPLER_PROJECT_FLAG,
        f"--config={config}",
        "--",
    ]


def main() -> None:
    """Run dev server with Doppler secrets (local config)."""
    import os

    # Set APP_ENV=local for consistency
    os.environ.setdefault("APP_ENV", "local")

    # Clear ENV_FILE to prevent .env from being loaded (Doppler provides secrets)
    os.environ["ENV_FILE"] = ""

    # Use doppler run to inject secrets from 'local' config
    # Note: --project must match your Doppler project name
    cmd = _doppler_run_prefix("local") + [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        *sys.argv[1:],
    ]
    run(cmd)


def test() -> None:
    """Run tests with Doppler secrets (test config)."""
    import os

    # Clear ENV_FILE to prevent .env from being loaded (Doppler provides secrets)
    os.environ["ENV_FILE"] = ""

    cmd = _doppler_run_prefix("test") + [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        *sys.argv[1:],
    ]
    run(cmd)


def test_local() -> None:
    """Run tests with Doppler secrets (local config - for local Docker testing)."""
    import os

    # Clear ENV_FILE to prevent .env from being loaded (Doppler provides secrets)
    os.environ["ENV_FILE"] = ""

    # Override SECURITY_SKIP_JWT_VALIDATION to disable for proper auth testing
    # This must be set BEFORE importing pytest to take effect
    # Using a bootstrap to ensure it's set early in the pytest process
    bootstrap = (
        "import os, sys; "
        "os.environ['SECURITY_SKIP_JWT_VALIDATION']='false'; "
        "import pytest; "
        "raise SystemExit(pytest.main(['-v', *sys.argv[1:]]))"
    )

    cmd = _doppler_run_prefix("local") + [sys.executable, "-c", bootstrap, *sys.argv[1:]]
    run(cmd)


def test_prod() -> None:
    """Run tests with Doppler secrets (prod config - production branch)."""
    import os

    # Clear ENV_FILE to prevent .env from being loaded (Doppler provides secrets)
    os.environ["ENV_FILE"] = ""

    # The prod config is meant for the production runtime, but we still want to run pytest
    # against the prod DB/URLs. Force APP_ENV=test inside the pytest process so production-only
    # config validation doesn't block test runs.
    bootstrap = (
        "import os, sys; "
        "os.environ['ENV_FILE']=''; "
        "os.environ['APP_ENV']='test'; "
        "import pytest; "
        "raise SystemExit(pytest.main(['-v', *sys.argv[1:]]))"
    )
    cmd = _doppler_run_prefix("prod") + [sys.executable, "-c", bootstrap, *sys.argv[1:]]
    run(cmd)


def autonomous_test() -> None:
    """Run autonomous live tests with Doppler secrets (local config)."""
    import os

    # Set APP_ENV=local for consistency
    os.environ.setdefault("APP_ENV", "local")

    # Clear ENV_FILE to prevent .env from being loaded (Doppler provides secrets)
    os.environ["ENV_FILE"] = ""

    # Run autonomous test script with Doppler secrets
    # Note: the script will handle starting/stopping infrastructure and server
    cmd = _doppler_run_prefix("local") + [
        sys.executable,
        "scripts/autonomous_live_test.py",
        *sys.argv[1:],
    ]
    run(cmd)


def autonomous_test_reset() -> None:
    """Run autonomous live tests with Doppler secrets and full DB reset (local config)."""
    import os

    # Set APP_ENV=local for consistency
    os.environ.setdefault("APP_ENV", "local")

    # Clear ENV_FILE to prevent .env from being loaded (Doppler provides secrets)
    os.environ["ENV_FILE"] = ""

    # Run autonomous test script with --reset flag
    cmd = _doppler_run_prefix("local") + [
        sys.executable,
        "scripts/autonomous_live_test.py",
        "--reset",
        *sys.argv[1:],
    ]
    run(cmd)
