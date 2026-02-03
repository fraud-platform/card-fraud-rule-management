"""CLI wrapper: Run tests with verbose output and Doppler."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run(["doppler", "run", "--", "python", "-m", "pytest", "-v", *sys.argv[1:]])
