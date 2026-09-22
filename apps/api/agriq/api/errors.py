"""Application-wide error handlers and security headers.

User-facing messages follow ``03_SECURITY_AND_ACCESS.md``; internal details
are logged but never returned to the browser.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.exceptions import AgriqError, InvalidCSRFError
from ..core.logging import get_logger

logger = get_logger("api.errors")

errors_bp = Blueprint("errors", __name__)

_WANTS_JSON_PREFIXES = ("/api/", "/ask-ai", "/healthz")


def _wants_json() -> bool:
    return request.path.startswith(tuple(_WANTS_JSON_PREFIXES))


@errors_bp.app_errorhandler(AgriqError)
def handle_agriq_error(exc: AgriqError):
    logger.warning("agriq_error type=%s path=%s", type(exc).__name__, request.path)
    if _wants_json():
        return jsonify({"ok": False, "error": exc.user_message}), exc.status_code
    return exc.user_message, exc.status_code


@errors_bp.app_errorhandler(InvalidCSRFError)
def handle_csrf(exc: InvalidCSRFError):
    return handle_agriq_error(exc)


@errors_bp.app_errorhandler(404)
def handle_404(_exc):
    if _wants_json():
        return jsonify({"ok": False, "error": "Not found."}), 404
    return "Page not found.", 404


@errors_bp.app_errorhandler(413)
def handle_413(_exc):
    message = "Upload too large. Use a clear JPG, PNG or WebP under 5 MiB."
    if _wants_json():
        return jsonify({"ok": False, "error": message}), 413
    return message, 413


@errors_bp.app_errorhandler(429)
def handle_429(_exc):
    message = "Too many requests. Please slow down and try again shortly."
    if _wants_json():
        return jsonify({"ok": False, "error": message}), 429
    return message, 429


@errors_bp.app_errorhandler(500)
def handle_500(exc):
    logger.error("internal_error path=%s", request.path)
    if _wants_json():
        return jsonify({"ok": False, "error": "An internal error occurred. Please try again."}), 500
    return "An internal error occurred. Please try again.", 500


@errors_bp.after_app_request
def apply_security_headers(response):
    """Baseline security headers (CSP, nosniff, frame denial, referrer)."""
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data: https://*.tile.openstreetmap.org https://tile.openstreetmap.org; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com; "
        "connect-src 'self' https://api.open-meteo.com; "
        "frame-ancestors 'none'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if response.status_code == 200 and request.path.startswith("/healthz"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response
