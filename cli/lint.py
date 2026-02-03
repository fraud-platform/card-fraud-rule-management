"""CLI wrapper: Run linter."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run([sys.executable, "-m", "ruff", "check", "app", "tests", "scripts", *sys.argv[1:]])
