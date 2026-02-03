"""CLI wrapper: Run E2E tests with Doppler."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run(
        [
            "doppler",
            "run",
            "--",
            "python",
            "-m",
            "pytest",
            "-m",
            "e2e_integration",
            "-v",
            *sys.argv[1:],
        ]
    )
