"""
Lightweight .env file loader.

This module provides a dependency-free .env parser for use across the application,
tests, and scripts. It intentionally avoids external dependencies like python-dotenv
to keep the dependency tree minimal.

Usage:
    from app.core.dotenv import load_env_file

    # Load default .env
    load_env_file()

    # Load specific file
    load_env_file(".env.production")

    # Load without overwriting existing vars (default)
    load_env_file(".env", overwrite=False)
"""

from __future__ import annotations

import os
from pathlib import Path


def _strip_inline_comment(value: str) -> str:
    """Remove inline comments from unquoted values.

    Examples:
        "value # comment" -> "value"
        '"value # not a comment"' -> '"value # not a comment"'
    """
    if not value or value[0] in ('"', "'"):
        return value

    for marker in (" #", "\t#"):
        idx = value.find(marker)
        if idx != -1:
            return value[:idx].rstrip()
    return value


def _unquote(value: str) -> str:
    """Remove surrounding quotes from a value.

    Examples:
        '"hello"' -> 'hello'
        "'hello'" -> 'hello'
        'hello' -> 'hello'
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single line from a .env file.

    Returns:
        Tuple of (key, value) or None if line should be skipped.
    """
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith("#") or "=" not in line:
        return None

    key, value = line.split("=", 1)
    key = key.strip()

    if not key:
        return None

    value = value.strip()
    value = _unquote(_strip_inline_comment(value))

    return key, value


def load_env_file(
    path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """Load environment variables from a .env file.

    Args:
        path: Path to .env file. If None, tries ".env" in current directory.
        overwrite: If True, overwrite existing environment variables.
                   If False (default), only set variables that aren't already set.

    Returns:
        Dictionary of variables that were loaded (for debugging/logging).

    Example:
        >>> load_env_file(".env")
        {'DATABASE_URL_APP': 'postgresql://...', 'AUTH0_DOMAIN': 'example.auth0.com'}
    """
    loaded: dict[str, str] = {}

    if path is None:
        path = Path(".env")
    else:
        path = Path(path)

    if not path.exists():
        return loaded

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(raw_line)
        if not parsed:
            continue

        key, value = parsed

        # Skip if already set and not overwriting
        if not overwrite and key in os.environ:
            continue

        os.environ[key] = value
        loaded[key] = value

    return loaded


def find_env_file(
    candidates: list[str] | None = None,
    start_dir: Path | None = None,
) -> Path | None:
    """Find the first existing .env file from a list of candidates.

    Args:
        candidates: List of filenames to try. Defaults to [".env", ".env.local"].
        start_dir: Directory to search in. Defaults to current working directory.

    Returns:
        Path to first existing file, or None if none found.
    """
    if candidates is None:
        candidates = [".env", ".env.local"]

    if start_dir is None:
        start_dir = Path.cwd()

    for candidate in candidates:
        path = start_dir / candidate
        if path.exists():
            return path

    return None
