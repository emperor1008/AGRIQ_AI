"""Local development launcher (root).

Adds ``apps/api`` to ``sys.path`` so ``agriq`` resolves, then starts the
Flask dev server on 127.0.0.1:5000. Production should use ``wsgi.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent / "apps" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq import create_app  # noqa: E402  (path set first intentionally)

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
