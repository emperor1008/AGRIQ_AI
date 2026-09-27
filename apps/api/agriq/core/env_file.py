"""Minimal ``.env`` loader for the entrypoints (Phase 7.1).

Before Phase 7.1 the repository documented a ``.env`` file that nothing ever
read: ``DATABASE_URL``/``AGRIQ_SECRET_KEY`` written there were silently ignored,
which is a genuine "wrong database / missing secret" class of login failure.

This loader is deliberately tiny and dependency-free (``python-dotenv`` is not
installed and is not worth adding for eleven lines of parsing):

- values already present in the real environment **always win**;
- the file is optional — a deployment that injects environment variables is
  unaffected;
- values are never logged, and no default secret is generated from the file.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["load_env_file", "DEFAULT_ENV_PATHS"]


def _candidate_paths() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    # apps/api/agriq/core/env_file.py → parents: core, agriq, api, apps, <repo>.
    # The repository root comes first; cwd is honoured too for container-style
    # layouts where the file is mounted next to the working directory.
    package_root = here.parents[2]  # apps/api
    return (
        here.parents[4] / ".env",        # <repo>/.env
        package_root / ".env",           # apps/api/.env
        Path.cwd() / ".env",
    )


DEFAULT_ENV_PATHS = _candidate_paths()


def _parse_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or text.startswith("["):
        return None
    if text.lower().startswith("export "):
        text = text[7:].strip()
    if "=" not in text:
        return None
    key, _, value = text.partition("=")
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_env_file(path: str | os.PathLike | None = None) -> int:
    """Load key/value pairs into ``os.environ`` without overriding it.

    Returns how many variables were applied. Missing files are not an error.
    """
    targets = (Path(path),) if path else DEFAULT_ENV_PATHS
    applied = 0
    for candidate in targets:
        try:
            raw_lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in raw_lines:
            parsed = _parse_line(line)
            if parsed is None:
                continue
            key, value = parsed
            if key in os.environ:  # real environment wins, always
                continue
            os.environ[key] = value
            applied += 1
    return applied
