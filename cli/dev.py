"""CLI wrapper: Start development server."""

from __future__ import annotations

import sys

from cli._runner import run


def main() -> None:
    run(
        [
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
    )
