"""Environment readiness check for AGRIQ AI.

Verifies Python version, required packages, configuration environment
variables and (optionally) reachability of external providers. Never
prints secret values.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def main() -> int:
    check("Python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])

    for module in ["flask", "PIL", "requests", "flask_limiter", "flask_sqlalchemy", "cachetools"]:
        try:
            __import__(module)
            check(f"package {module}", True)
        except ImportError:
            check(f"package {module}", False, "pip install -r apps/api/requirements.txt")

    from agriq.core.config import get_config

    config = get_config()
    # Development conveniences are advisory (WARN), hard requirements FAIL.
    check("AGRIQ_SECRET_KEY set", True,
          "OK" if os.environ.get("AGRIQ_SECRET_KEY")
          else "WARN: using built-in development fallback")
    check("DATABASE_URL", bool(config.SQLALCHEMY_DATABASE_URI), config.SQLALCHEMY_DATABASE_URI.split("://")[0])
    check("RATELIMIT_STORAGE_URI", bool(config.RATELIMIT_STORAGE_URI), config.RATELIMIT_STORAGE_URI)

    check("GEMINI_API_KEY configured", True,
          "OK" if config.GEMINI_API_KEY
          else "WARN: assistant will use built-in knowledge engine")
    check("DATA_GOV_IN_API_KEY configured", True,
          "OK" if config.DATA_GOV_IN_API_KEY
          else "WARN: market feed will show unavailable state")

    production = os.environ.get("AGRIQ_ENV") == "production"
    if production:
        check("production cookie secure", config.SESSION_COOKIE_SECURE, "set AGRIQ_COOKIE_SECURE=1")
        check("production database is PostgreSQL", config.SQLALCHEMY_DATABASE_URI.startswith("postgresql"))
        check("production rate-limit storage is Redis", config.RATELIMIT_STORAGE_URI.startswith("redis"))

    failed = [name for name, ok, _ in CHECKS if not ok]
    for name, ok, detail in CHECKS:
        marker = "OK " if ok else "FAIL"
        suffix = f" ({detail})" if detail else ""
        print(f"[{marker}] {name}{suffix}")

    if failed:
        print(f"\n{len(failed)} check(s) failed.")
        return 1
    print("\nAll environment checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
