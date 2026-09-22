"""Application logging setup.

Standard-library logging with a concise formatter. Secrets and passwords
are never logged anywhere in the codebase; providers only receive the
generic event metadata required for diagnosis.
"""
from __future__ import annotations

import logging
import sys

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: int | None = None) -> None:
    """Configure root logging once for the process."""
    if level is None:
        level = logging.DEBUG if sys.flags.debug else logging.INFO
    root = logging.getLogger()
    if root.handlers:  # already configured (e.g. by pytest or gunicorn)
        root.setLevel(level)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger helper."""
    return logging.getLogger(f"agriq.{name}")


__all__ = ["configure_logging", "get_logger"]
