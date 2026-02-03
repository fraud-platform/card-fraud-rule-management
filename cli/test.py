"""CLI wrapper: Run unit tests with Doppler."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run(["doppler", "run", "--", "python", "-m", "pytest", "-q", *sys.argv[1:]])
