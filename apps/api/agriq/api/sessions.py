"""Authenticated account-security API (Phase 7.1).

- ``GET  /api/v1/auth/sessions``                 → the caller's own sessions
- ``POST /api/v1/auth/sessions/<id>/revoke``     → revoke one of *their* sessions
- ``POST /api/v1/auth/password``                 → change password (revokes others)

Every route resolves its identity from the server-side session (§19) and is
scoped to that user, so a session id from another account is a 404, never a
cross-user action. All state-changing routes require the CSRF token.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.audit import audit_event
from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.security import (
    current_session_id,
    get_current_user,
    logout_user_session,
    require_csrf,
)
from ..repositories.session_repository import SessionRepository
from ..services.authentication import change_password

logger = get_logger("api.sessions")

sessions_bp = Blueprint("sessions", __name__)


@sessions_bp.get("/api/v1/auth/sessions")
def list_sessions():
    """List the authenticated user's own sessions (never anyone else's)."""
    user = get_current_user()
    current_id = current_session_id()
    rows = SessionRepository.list_for_user(user.id)
    return jsonify({
        "ok": True,
        "sessions": [row.to_dict(current=row.id == current_id) for row in rows],
    })


@sessions_bp.post("/api/v1/auth/sessions/<int:session_id>/revoke")
@require_csrf
def revoke_session(session_id: int):
    """Revoke one of the caller's sessions; signing out the current one too."""
    user = get_current_user()
    row = SessionRepository.get_by_id(session_id, user.id)
    if row is None:
        # Someone else's session id and a non-existent id are indistinguishable.
        raise NotFoundError("That session was not found.")
    current_id = current_session_id()
    SessionRepository.revoke(row, "user_revoked")
    audit_event("session_revoked", user_id=user.id, session_id=row.id)
    signed_out = row.id == current_id
    if signed_out:
        logout_user_session("user_revoked")
    return jsonify({"ok": True, "revoked": row.id, "signed_out": signed_out})


@sessions_bp.post("/api/v1/auth/password")
@require_csrf
def update_password():
    """Change the password of the signed-in user, revoking their other sessions."""
    user = get_current_user()
    payload = request.get_json(silent=True) or request.form
    current = payload.get("current_password")
    new = payload.get("password")
    confirm = payload.get("password_confirm")
    if not current or not new:
        raise ValidationError("Enter your current password and the new password.")
    result = change_password(user, str(current), str(new), str(confirm or ""))
    if not result.ok:
        audit_event("password_change_rejected", user_id=user.id, code=result.code)
        return jsonify({"ok": False, "error": result.message, "code": result.code}), 400
    # change_password() revoked every live session, including this one: the
    # cookie is cleared so the client must sign in again with the new password.
    logout_user_session("password_change")
    return jsonify({"ok": True, "message": result.message, "reauthenticate": True})


__all__ = ["sessions_bp"]
