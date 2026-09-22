"""Convenience test runner: pytest for the AGRIQ AI API suite.

Usage::

    python scripts/run_tests.py              # full suite
    python scripts/run_tests.py unit         # tests/unit only
    python scripts/run_tests.py integration  # tests/integration only
    python scripts/run_tests.py security     # tests/security only
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"


def main() -> int:
    scope = sys.argv[1] if len(sys.argv) > 1 else None
    target = f"tests/{scope}" if scope else "tests"
    command = [sys.executable, "-m", "pytest", target, *sys.argv[2:]]
    print("Running:", " ".join(command))
    return subprocess.call(command, cwd=API_ROOT)


if __name__ == "__main__":
    sys.exit(main())
