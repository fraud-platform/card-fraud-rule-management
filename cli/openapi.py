"""CLI wrapper: Generate OpenAPI specification."""

from __future__ import annotations

import sys
from pathlib import Path

from cli._runner import run


def main() -> None:
    script = Path(__file__).parent.parent / "scripts" / "generate_openapi.py"
    run([sys.executable, str(script), *sys.argv[1:]])
