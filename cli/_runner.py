"""
Shared CLI runner helper.

This module provides a standard way to run commands inside the uv-managed
environment, ensuring consistent behavior across all CLI wrappers.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


def run(cmd: Sequence[str]) -> None:
    """
    Run a command inside the uv-managed environment.

    The command's exit code will be propagated to the caller.

    Args:
        cmd: Command and arguments to execute

    Example:
        >>> run([sys.executable, "-m", "pytest", "-q"])
    """
    result = subprocess.run(cmd)
    raise SystemExit(result.returncode)
