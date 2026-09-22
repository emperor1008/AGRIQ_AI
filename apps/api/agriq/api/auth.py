"""Authentication + workspace-selection blueprints.

Routes kept compatible with the legacy prototype:
- ``GET  /``            → login page (or redirect to /choose)
- ``POST /login``       → sign in (and register-on-first-login fallback)
- ``GET  /choose``      → workspace chooser
- ``POST /choose-mode`` → farmer/student selection
- ``POST /logout``      → logout (POST + CSRF; legacy GET still redirects)
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from ..core.constants import DEFAULT_MODE, MODE_FARMER, MODE_STUDENT, SESSION_USER_KEY
from ..core.logging import get_logger
from ..core.security import (
    get_csrf_token,
    is_authenticated,
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


@auth_bp.get("/")
def index():
    if is_authenticated():
        return redirect(url_for("auth.choose"))
    return render_template("auth/login.html", page="login", csrf_token=get_csrf_token())


@auth_bp.post("/login")
def login():
    """Sign in with real credentials (Phase 1 accounts).

    The prototype's transparent register-on-first-login path is replaced by
    real accounts: a contact is registered only through the explicit
    register step (password required, scrypt-hashed). Login failure always
    returns the same generic message — no account enumeration.
    """
    credentials = parse_credentials(
        request.form.get("user_contact"), request.form.get("password")
    )
    contact_value = form_value(request.form, "user_contact", "", 120)

    # --- Registration path (explicit password confirm field) ---------------
    confirm_value = form_value(request.form, "password_confirm", "", 128)
    if credentials.valid_contact and confirm_value and request.form.get("password"):
        result = register(credentials.contact, request.form.get("password"))
        if result.ok:
            # Generic success; the user then signs in normally.
            return render_template(
                "auth/login.html", page="login",
                success=result.message, csrf_token=get_csrf_token(),
            )
        return render_template(
            "auth/login.html", page="login", error=result.message, csrf_token=get_csrf_token()
        )

    # --- Sign-in path -------------------------------------------------------
    if credentials.valid_contact and request.form.get("password"):
        result = authenticate(credentials.contact, credentials.password)
        if result.ok:
            user = UserRepository.get_by_contact(credentials.contact)
            if user is not None and not user.is_active:
                return render_template(
                    "auth/login.html", page="login",
                    error="Invalid contact or password.", csrf_token=get_csrf_token(),
                )
            if user is not None:
                UserRepository.touch_last_login(user)
            login_user_session(result.user_contact or credentials.contact)
            return redirect(url_for("auth.choose"))
        return render_template(
            "auth/login.html", page="login", error=result.message, csrf_token=get_csrf_token()
        )

    if contact_value and not request.form.get("password"):
        return render_template(
            "auth/login.html", page="login",
            error="Enter your password. New here? Add a password to create your account.",
            csrf_token=get_csrf_token(),
        )

    return render_template(
        "auth/login.html", page="login", error="Enter your email or phone number.",
        csrf_token=get_csrf_token(),
    )


@auth_bp.get("/choose")
def choose():
    if not is_authenticated():
        return redirect(url_for("auth.index"))
    return render_template(
        "auth/choose.html",
        page="choose",
        user_contact=session.get(SESSION_USER_KEY),
        csrf_token=get_csrf_token(),
    )


@auth_bp.post("/choose-mode")
def choose_mode():
    if not is_authenticated():
        return redirect(url_for("auth.index"))
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not verify_csrf(token):
        return render_template(
            "auth/choose.html", page="choose", user_contact=session.get(SESSION_USER_KEY),
            error="Invalid or missing CSRF token.", csrf_token=get_csrf_token(),
        ), 400
    mode = request.form.get("mode", DEFAULT_MODE)
    if mode not in {MODE_FARMER, MODE_STUDENT}:
        mode = DEFAULT_MODE
    set_user_mode(mode)
    return redirect(url_for("dashboard.dashboard"))


@auth_bp.route("/logout", methods=["POST", "GET"])
def logout():
    """POST + CSRF preferred; plain GET kept for legacy side-rail link."""
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if session.get(SESSION_USER_KEY) is not None and not verify_csrf(token):
            return render_template(
                "auth/choose.html", page="choose", user_contact=session.get(SESSION_USER_KEY),
                error="Invalid or missing CSRF token.", csrf_token=get_csrf_token(),
            ), 400
    logout_user_session()
    return redirect(url_for("auth.index"))
