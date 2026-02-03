"""CLI wrapper: Format code."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run([sys.executable, "-m", "ruff", "format", "app", "tests", "scripts", *sys.argv[1:]])
