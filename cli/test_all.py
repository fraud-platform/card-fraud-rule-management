"""CLI wrapper: Run all tests including E2E with Doppler."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run(["doppler", "run", "--", "python", "-m", "pytest", "-m", "", "-v", *sys.argv[1:]])
