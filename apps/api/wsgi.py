"""Production WSGI entrypoint for Gunicorn.

    gunicorn --chdir apps/api --bind 0.0.0.0:8000 --workers 2 --threads 4 wsgi:app

Phase 7.1: the optional ``.env`` file is loaded *before* the app reads its
configuration. Real environment variables always win, so a container that
injects secrets is unaffected — but a host that relies on ``.env`` (as the
repository's own documentation promised) is no longer silently ignored.
"""
import sys
from pathlib import Path

# The ``ml`` package lives at the REPOSITORY root (the Dockerfile copies it to
# /app/ml), not inside apps/api. Without this the image capability probe raised
# ModuleNotFoundError and answered 500 instead of its honest "not available".
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agriq.core.env_file import load_env_file  # noqa: E402  (path set first)

load_env_file()

from agriq import create_app  # noqa: E402  (env must be loaded first)

app = create_app()
