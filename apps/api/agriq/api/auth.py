"""Authentication + workspace-selection blueprints.

Routes (Phase 7.1):

- ``GET  /``              → login page (or redirect to /choose)
- ``GET  /login``         → login page (this route did not exist before 7.1,
                            which made every refresh at /login a bare 405)
- ``GET  /login?mode=register`` → same page with the account fields visible
- ``POST /login``         → sign in, or register when the account form is used
- ``GET  /choose``        → workspace chooser
- ``POST /choose-mode``   → farmer/student selection
- ``POST /logout``        → revoke the session (GET kept for the legacy link)

Password recovery lives in ``api.recovery`` (separate blueprint) and active
sessions in ``api.sessions``. Registration requires the password to be repeated
and verified server-side; failures carry a stable ``AUTH_*`` code so the page can
explain what happened without revealing whether an account exists.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from ..core.audit import audit_event
from ..core.constants import DEFAULT_MODE, MODE_FARMER, MODE_STUDENT
from ..core.logging import get_logger
from ..core.security import (
    enforce_allowed_origin,
    get_csrf_token,
    is_authenticated,
    login_csrf_ok,
    login_user_session,
    logout_user_session,
    set_user_mode,
    verify_csrf,
)
from ..repositories.user_repository import UserRepository
from ..schemas.auth import parse_credentials
from ..schemas.common import form_value
from ..services.authentication import authenticate, register

logger = get_logger("api.auth")

auth_bp = Blueprint("auth", __name__)


def _login_context(**extra) -> dict:
    context = {"page": "login", "csrf_token": get_csrf_token()}
    context.update(extra)
    return context


def _render_login(**extra):
    return render_template("auth/login.html", **_login_context(**extra))


def _client_ip() -> str | None:
    return request.remote_addr


@auth_bp.get("/")
def index():
    """Login page for guests; signed-in users go straight to workspace choice."""
    if is_authenticated():
        return redirect(url_for("auth.choose"))
    return _render_login()


@auth_bp.get("/login")
def login_page():
    """Serve the login form on ``GET /login``.

    Phase 7.1 root-cause fix: before this route existed, ``/login`` was POST-only,
    so reloading the page after any failed sign-in (the browser was sitting at
    ``/login``) returned ``405 Method Not Allowed`` with no AGRIQ chrome — the
    reported "login error". The page is also directly bookmarkable now.
    """
    if is_authenticated():
        return redirect(url_for("auth.choose"))
    register_mode = (request.args.get("mode") or "").strip().lower() == "register"
    return _render_login(register_mode=register_mode)


@auth_bp.post("/login")
def login():
    """Sign in with real credentials, or register through the account form.

    Rate-limited by ``AGRIQ_RATE_LOGIN`` (default 8/minute per IP), which covers
    both sign-in and registration attempts from the same address.
    """
    enforce_allowed_origin()

    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not login_csrf_ok(token):
        audit_event("login_csrf_rejected", ip=_client_ip())
        return (
            _render_login(
                error="Your sign-in form expired. Please try again.",
                error_code="CSRF_REJECTED",
            ),
            400,
        )

    credentials = parse_credentials(
        request.form.get("user_contact"), request.form.get("password")
    )
    contact_value = form_value(request.form, "user_contact", "", 120)
    confirm_value = form_value(request.form, "password_confirm", "", 128)
    # Explicit intent where the form provides it; the confirm field is kept as a
    # fallback so older cached pages keep working.
    registering = (request.form.get("auth_action") or "").strip().lower() == "register"
    if not registering:
        registering = bool(confirm_value)

    # --- Registration path ------------------------------------------------
    if registering:
        if not credentials.valid_contact:
            return _render_login(
                error="Enter a valid email or phone number.",
                error_code="AUTH_VALIDATION", register_mode=True,
            )
        result = register(
            credentials.contact, request.form.get("password"), confirm_value
        )
        if result.ok:
            return _render_login(success=result.message, register_mode=False)
        return _render_login(error=result.message, error_code=result.code, register_mode=True)

    # --- Sign-in path ------------------------------------------------------
    if credentials.valid_contact and request.form.get("password"):
        result = authenticate(credentials.contact, credentials.password)
        if result.ok:
            user = UserRepository.get_by_contact(credentials.contact)
            if user is None:
                # Raced by a concurrent delete: fail closed, never fake a login.
                logger.warning("login_user_vanished")
                return _render_login(
                    error="Invalid contact or password.",
                    error_code="AUTH_INVALID_CREDENTIALS",
                )
            UserRepository.touch_last_login(user)
            login_user_session(user)
            audit_event("login_success", user_id=user.id, ip=_client_ip())
            return redirect(url_for("auth.choose"))
        return _render_login(error=result.message, error_code=result.code)

    if contact_value and not request.form.get("password"):
        return _render_login(
            error="Enter your password. New here? Add a password to create your account.",
            error_code="AUTH_VALIDATION",
        )

    return _render_login(
        error="Enter your email or phone number.", error_code="AUTH_VALIDATION"
    )


@auth_bp.get("/choose")
def choose():
    if not is_authenticated():
        return redirect(url_for("auth.index"))
    return render_template(
        "auth/choose.html",
        page="choose",
        user_contact=_session_contact(),
        csrf_token=get_csrf_token(),
    )


@auth_bp.post("/choose-mode")
def choose_mode():
    if not is_authenticated():
        return redirect(url_for("auth.index"))
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not verify_csrf(token):
        audit_event("choose_mode_csrf_rejected", ip=_client_ip())
        return (
            render_template(
                "auth/choose.html", page="choose",
                user_contact=_session_contact(),
                error="Invalid or missing CSRF token.", csrf_token=get_csrf_token(),
            ),
            400,
        )
    mode = request.form.get("mode", DEFAULT_MODE)
    if mode not in {MODE_FARMER, MODE_STUDENT}:
        mode = DEFAULT_MODE
    set_user_mode(mode)
    audit_event("workspace_selected", mode=mode)
    return redirect(url_for("dashboard.dashboard"))


def _session_contact() -> str | None:
    """Contact of the authenticated user for display (never a browser value)."""
    from ..core.security import current_user

    user = current_user()
    return user.contact if user else None


@auth_bp.route("/logout", methods=["POST", "GET"])
def logout():
    """Revoke the server-side session, then clear the cookie.

    POST + CSRF is the supported path; ``GET`` remains for the legacy side-rail
    link. Either way the session row is revoked, so the cookie cannot be replayed.
    """
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if is_authenticated() and not verify_csrf(token):
            audit_event("logout_csrf_rejected", ip=_client_ip())
            return (
                render_template(
                    "auth/choose.html", page="choose", user_contact=_session_contact(),
                    error="Invalid or missing CSRF token.", csrf_token=get_csrf_token(),
                ),
                400,
            )
    revoked = logout_user_session()
    audit_event("logout", revoked=revoked, ip=_client_ip())
    return redirect(url_for("auth.index"))


__all__ = ["auth_bp"]
