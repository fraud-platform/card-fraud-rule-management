"""CLI wrapper: Run smoke tests with Doppler."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run(["doppler", "run", "--", "python", "-m", "pytest", "-m", "smoke", "-v", *sys.argv[1:]])
