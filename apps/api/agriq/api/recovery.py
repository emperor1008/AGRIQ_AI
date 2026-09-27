"""Password recovery blueprint (Phase 7.1).

- ``GET  /forgot-password``  → request form
- ``POST /forgot-password``  → request a reset link (generic answer; honest
                              ``PASSWORD_RESET_EMAIL_UNAVAILABLE`` when no email
                              provider is configured)
- ``GET  /reset-password``   → set-new-password form (token from the link)
- ``POST /reset-password``   → consume the token, store the new scrypt hash and
                              revoke every existing session

Both POST routes are CSRF-checked when a session nonce exists and rate-limited;
neither ever reports a message as sent unless a provider accepted it.
"""
from __future__ import annotations

from flask import Blueprint, current_app, render_template, request

from ..core.audit import audit_event
from ..core.logging import get_logger
from ..core.security import enforce_allowed_origin, get_csrf_token, login_csrf_ok
from ..schemas.common import form_value
from ..services import password_reset

logger = get_logger("api.recovery")

recovery_bp = Blueprint("recovery", __name__)


def _context(**extra) -> dict:
    context = {"page": "login", "csrf_token": get_csrf_token()}
    context.update(extra)
    return context


@recovery_bp.get("/forgot-password")
def forgot_password_page():
    return render_template("auth/forgot_password.html", **_context())


@recovery_bp.post("/forgot-password")
def forgot_password():
    enforce_allowed_origin()
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not login_csrf_ok(token):
        return (
            render_template(
                "auth/forgot_password.html",
                **_context(error="Your form expired. Please try again.", error_code="CSRF_REJECTED"),
            ),
            400,
        )

    contact = form_value(request.form, "user_contact", "", 120)
    result = password_reset.request_reset(
        contact, config=current_app.config, address=request.remote_addr
    )
    return render_template(
        "auth/forgot_password.html",
        **_context(
            notice=result.message,
            ok=result.ok,
            status_code=result.code,
            user_contact=contact,
        ),
    )


@recovery_bp.get("/reset-password")
def reset_password_page():
    token = (request.args.get("token") or "").strip()
    if not token:
        return (
            render_template(
                "auth/reset_password.html",
                **_context(
                    error="That reset link is incomplete. Request a new one.",
                    error_code="AUTH_INVALID_RESET_TOKEN",
                ),
            ),
            400,
        )
    return render_template("auth/reset_password.html", **_context(token=token))


@recovery_bp.post("/reset-password")
def reset_password():
    enforce_allowed_origin()
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not login_csrf_ok(token):
        return (
            render_template(
                "auth/reset_password.html",
                **_context(
                    error="Your form expired. Please try again.", error_code="CSRF_REJECTED"
                ),
            ),
            400,
        )

    raw_token = form_value(request.form, "token", "", 200)
    result = password_reset.confirm_reset(
        raw_token, request.form.get("password"), request.form.get("password_confirm")
    )
    if result.ok:
        audit_event("password_reset_form_completed")
        # Report the real outcome on the sign-in page rather than silently
        # redirecting: the farmer must know the password was changed.
        return render_template(
            "auth/login.html", page="login", csrf_token=get_csrf_token(),
            success=result.message,
        )
    return render_template(
        "auth/reset_password.html",
        **_context(error=result.message, error_code=result.code, token=raw_token),
    )


__all__ = ["recovery_bp"]
