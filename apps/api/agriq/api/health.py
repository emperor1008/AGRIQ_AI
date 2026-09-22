"""Health check endpoint (GET /healthz)."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..core.time import now_ist

health_bp = Blueprint("health", __name__)


@health_bp.get("/healthz")
def healthz():
    """Liveness probe: no external provider calls, no secrets in response."""
    return jsonify({"status": "ok", "service": "agriq-ai", "time": now_ist().isoformat()})
