"""
Autonomous Live Test Suite - CLI wrapper.

Entry point for the autonomous-live-test command.
Delegates to the main script.
"""

import sys  # noqa: E402 (needed before path insert)
from pathlib import Path
from sys import argv

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.autonomous_live_test import main  # noqa: E402 (import after path setup)

if __name__ == "__main__":
    sys.exit(main(argv[1:]))
