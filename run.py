"""Local development launcher (root).

Adds ``apps/api`` to ``sys.path`` so ``agriq`` resolves, loads the optional
``.env`` file, then starts the Flask dev server on 127.0.0.1:5000.
Production should use ``wsgi.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
API_DIR = REPO_ROOT / "apps" / "api"
for entry in (str(REPO_ROOT), str(API_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
# REPO_ROOT is on the path because the ``ml`` package lives at the repository
# root; without it the image capability probe answers 500 in local runs.

from agriq.core.env_file import load_env_file  # noqa: E402  (path set first)

# Phase 7.1: honour the documented .env file before configuration is read.
# Variables already present in the environment always take precedence.
load_env_file()

from agriq import create_app  # noqa: E402  (env must be loaded first)

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
