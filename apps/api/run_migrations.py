"""Migration runner: apply Alembic migrations to the configured database.

Usage (from apps/api)::

    python run_migrations.py upgrade      # apply all pending migrations
    python run_migrations.py downgrade    # revert one revision
    python run_migrations.py current      # show current revision
"""
from __future__ import annotations

import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    if action == "upgrade":
        command.upgrade(cfg, "head")
    elif action == "downgrade":
        command.downgrade(cfg, "-1")
    elif action == "current":
        command.current(cfg)
    else:
        print(f"Unknown action: {action}. Use upgrade | downgrade | current.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
