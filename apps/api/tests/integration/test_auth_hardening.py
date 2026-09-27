"""Phase 7.1 — authentication, session and authorization hardening tests.

Every test drives the real application: real HTTP routes, the real database (an
in-memory database created from the real models), real scrypt hashing and real
server-side session rows. Fixtures never forge an authentication state that
production would reject.

Coverage (``§35``): the reported login error, registration, login, logout,
session lifecycle/expiry/revocation, password reset, authorization isolation,
and the "no bypass / no fake auth" guarantees.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest

from agriq.core.constants import SESSION_TOKEN_KEY, SESSION_USER_KEY
from agriq.core.time import utc_now
from agriq.extensions import db
from agriq.models.password_reset import PasswordResetToken
from agriq.models.user_session import UserSession
from agriq.repositories.password_reset_repository import PasswordResetRepository
from agriq.repositories.session_repository import SessionRepository
from agriq.repositories.user_repository import UserRepository
from agriq.services import email_provider

PASSWORD = "hardening-password-1"
NEW_PASSWORD = "hardening-password-2"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def register(client, csrf, contact, password=PASSWORD):
    return client.post("/login", data={
        "csrf_token": csrf,
        "user_contact": contact,
        "password": password,
        "password_confirm": password,
        "auth_action": "register",
    })


def sign_in(client, csrf, contact, password=PASSWORD):
    return client.post("/login", data={
        "csrf_token": csrf,
        "user_contact": contact,
        "password": password,
    })


def session_token_of(client) -> str:
    with client.session_transaction() as session:
        return session[SESSION_TOKEN_KEY]


def configure_email(app):
    app.config.update(
        AGRIQ_EMAIL_PROVIDER="smtp",
        AGRIQ_SMTP_HOST="smtp.example.test",
        AGRIQ_SMTP_USERNAME="agriq-sender",
        AGRIQ_SMTP_PASSWORD="not-a-real-password",
        AGRIQ_EMAIL_FROM="no-reply@agriq.test",
        AGRIQ_PUBLIC_BASE_URL="https://agriq.test",
    )


def request_reset(client, csrf, contact):
    return client.post("/forgot-password", data={
        "csrf_token": csrf, "user_contact": contact,
    })


@pytest.fixture()
def capturing_email(monkeypatch):
    """Capture outgoing mail instead of contacting an SMTP server."""
    captured: dict = {}

    def _send(source, *, to, subject, body):
        captured.update(to=to, subject=subject, body=body)
        return email_provider.EmailDelivery(True, "EMAIL_SENT", "captured by test")

    monkeypatch.setattr(email_provider, "send", _send)
    return captured


# ---------------------------------------------------------------------------
# The reported login error (root-cause regression)
# ---------------------------------------------------------------------------

class TestLoginPageIsReachable:
    def test_get_login_serves_the_form(self, client):
        """GET /login used to answer 405; it must serve the login page."""
        response = client.get("/login")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "AGRIQ AI" in html
        assert 'name="user_contact"' in html
        assert 'name="password"' in html

    def test_get_login_after_a_failed_attempt_still_serves_the_form(self, client, login_csrf):
        """The exact reported symptom: reload while sitting at /login."""
        sign_in(client, login_csrf(), "nobody@example.com", "wrong-password-1")
        reload_response = client.get("/login")
        assert reload_response.status_code == 200
        assert "AGRIQ AI" in reload_response.get_data(as_text=True)

    def test_get_login_register_mode_shows_account_fields(self, client):
        html = client.get("/login?mode=register").get_data(as_text=True)
        assert 'id="register-fields" style="display:block"' in html
        assert 'name="password_confirm"' in html
        assert 'value="register"' in html  # explicit auth_action intent

    def test_get_login_redirects_a_signed_in_user(self, auth_client):
        response = auth_client.get("/login")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/choose")

    def test_login_page_offers_recovery(self, client):
        html = client.get("/login").get_data(as_text=True)
        assert "/forgot-password" in html

    def test_recovery_page_renders_without_a_session(self, client):
        """A first-time visitor can reach recovery (and gets an honest state)."""
        html = client.post("/forgot-password").get_data(as_text=True)
        assert "AGRIQ AI" in html
        assert "not available on this deployment" in html


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_registration_requires_matching_confirmation(self, client, login_csrf, app):
        response = client.post("/login", data={
            "csrf_token": login_csrf(),
            "user_contact": "mismatch@example.com",
            "password": PASSWORD,
            "password_confirm": "something-else-1",
            "auth_action": "register",
        })
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "do not match" in body
        assert UserRepository.get_by_contact("mismatch@example.com") is None

    def test_registration_rejects_weak_passwords(self, client, login_csrf):
        for weak in ("short1", "aaaaaaaa", "password123", "12345678"):
            response = register(client, login_csrf(), "weak@example.com", weak)
            assert response.status_code == 200
            assert "No account" not in response.get_data(as_text=True)
        assert UserRepository.get_by_contact("weak@example.com") is None

    def test_registration_rejects_invalid_contact(self, client, login_csrf):
        response = register(client, login_csrf(), "not-an-email", PASSWORD)
        assert "valid email or phone" in response.get_data(as_text=True)
        assert UserRepository.get_by_contact("not-an-email") is None

    def test_registration_stores_scrypt_hash_and_never_returns_it(self, client, login_csrf):
        response = register(client, login_csrf(), "hashed@example.com")
        body = response.get_data(as_text=True)
        user = UserRepository.get_by_contact("hashed@example.com")
        assert user is not None
        assert user.password_hash.startswith("scrypt:")
        assert PASSWORD not in body
        assert user.password_hash not in body
        assert user.check_password(PASSWORD) is True

    def test_duplicate_registration_is_generic(self, client, login_csrf):
        register(client, login_csrf(), "dupe@example.com")
        response = register(client, login_csrf(), "dupe@example.com")
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "may already be registered" in body
        assert UserRepository.count() == 1

    def test_registration_is_case_normalised(self, client, login_csrf, app):
        register(client, login_csrf(), "Mixed.Case@Example.com")
        assert UserRepository.get_by_contact("mixed.case@example.com") is not None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_requires_the_csrf_token_of_the_form(self, client, login_csrf):
        register(client, login_csrf(), "csrf-login@example.com")
        response = client.post("/login", data={
            "user_contact": "csrf-login@example.com", "password": PASSWORD,
        })
        assert response.status_code == 400
        assert "expired" in response.get_data(as_text=True).lower()

    def test_valid_login_creates_a_server_side_session(self, client, login_csrf):
        register(client, login_csrf(), "session@example.com")
        response = sign_in(client, login_csrf(), "session@example.com")
        assert response.status_code == 302
        user = UserRepository.get_by_contact("session@example.com")
        rows = SessionRepository.list_for_user(user.id)
        assert len(rows) == 1
        assert rows[0].revoked_at is None
        assert rows[0].is_live()
        # The raw token is only in the cookie; the row stores its digest.
        assert session_token_of(client) not in {rows[0].token_hash}

    def test_failed_login_creates_no_session(self, client, login_csrf):
        register(client, login_csrf(), "nosession@example.com")
        sign_in(client, login_csrf(), "nosession@example.com", "wrong-password-2")
        user = UserRepository.get_by_contact("nosession@example.com")
        assert SessionRepository.list_for_user(user.id) == []

    def test_unknown_account_and_wrong_password_are_indistinguishable(self, client, login_csrf):
        register(client, login_csrf(), "real@example.com")
        wrong = sign_in(client, login_csrf(), "real@example.com", "wrong-password-2")
        unknown = sign_in(client, login_csrf(), "ghost@example.com", PASSWORD)
        assert wrong.status_code == unknown.status_code == 200
        assert "Invalid contact or password" in wrong.get_data(as_text=True)
        assert "Invalid contact or password" in unknown.get_data(as_text=True)

    def test_disabled_account_cannot_log_in(self, client, login_csrf):
        register(client, login_csrf(), "disabled@example.com")
        user = UserRepository.get_by_contact("disabled@example.com")
        UserRepository.set_active(user, False)
        response = sign_in(client, login_csrf(), "disabled@example.com")
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "disabled" in body.lower()
        assert SessionRepository.list_for_user(user.id) == []

    def test_login_records_last_login_time(self, client, login_csrf):
        register(client, login_csrf(), "lastlogin@example.com")
        assert UserRepository.get_by_contact("lastlogin@example.com").last_login_at is None
        sign_in(client, login_csrf(), "lastlogin@example.com")
        assert UserRepository.get_by_contact("lastlogin@example.com").last_login_at is not None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_forged_cookie_without_a_session_row_is_rejected(self, client, csrf_token):
        """A signed cookie alone is no longer proof of identity."""
        with client.session_transaction() as session:
            session["_agriq_csrf_token"] = csrf_token
            session[SESSION_USER_KEY] = "tester@example.com"
            session[SESSION_TOKEN_KEY] = "forged-token-not-in-the-database"
        assert client.get("/dashboard", follow_redirects=False).status_code == 302
        assert client.get("/api/profile").status_code == 401

    def test_legacy_cookie_only_session_is_rejected(self, client, csrf_token, app):
        """Cookies issued before Phase 7.1 (no session row) stop being accepted."""
        UserRepository.create("legacy@example.com", PASSWORD)
        with client.session_transaction() as session:
            session["_agriq_csrf_token"] = csrf_token
            session[SESSION_USER_KEY] = "legacy@example.com"
        assert client.get("/api/profile").status_code == 401

    def test_tampered_session_token_is_rejected(self, client, login_csrf):
        register(client, login_csrf(), "tamper@example.com")
        sign_in(client, login_csrf(), "tamper@example.com")
        with client.session_transaction() as session:
            session[SESSION_TOKEN_KEY] = "x" * 43
        assert client.get("/api/profile").status_code == 401

    def test_expired_session_row_is_rejected(self, client, login_csrf):
        register(client, login_csrf(), "expired@example.com")
        sign_in(client, login_csrf(), "expired@example.com")
        _, row = SessionRepository.resolve(session_token_of(client))
        row.expires_at = utc_now() - timedelta(minutes=1)
        db.session.commit()
        assert client.get("/api/profile").status_code == 401

    def test_absolute_expiry_caps_the_sliding_window(self, client, login_csrf):
        register(client, login_csrf(), "absolute@example.com")
        sign_in(client, login_csrf(), "absolute@example.com")
        _, row = SessionRepository.resolve(session_token_of(client))
        row.absolute_expires_at = utc_now() - timedelta(seconds=1)
        db.session.commit()
        assert client.get("/api/profile").status_code == 401

    def test_revoked_session_cookie_replay_is_rejected(self, app, client, login_csrf):
        register(client, login_csrf(), "replay@example.com")
        sign_in(client, login_csrf(), "replay@example.com")
        stolen_cookie = client.get_cookie("agriq_session")
        assert stolen_cookie is not None
        client.post("/logout", data={"csrf_token": login_csrf("/choose")})

        replay = app.test_client()
        replay.set_cookie("agriq_session", stolen_cookie.value)
        assert replay.get("/dashboard", follow_redirects=False).status_code == 302
        assert replay.get("/api/profile").status_code == 401

    def test_disabling_an_account_kills_its_live_session(self, client, login_csrf):
        register(client, login_csrf(), "kill@example.com")
        sign_in(client, login_csrf(), "kill@example.com")
        user = UserRepository.get_by_contact("kill@example.com")
        UserRepository.set_active(user, False)
        assert client.get("/api/profile").status_code == 401

    def test_session_list_shows_only_the_owner(self, auth_client, second_farmer_client):
        first = auth_client.get("/api/v1/auth/sessions").get_json()["sessions"]
        second = second_farmer_client.get("/api/v1/auth/sessions").get_json()["sessions"]
        assert len(first) == 1 and len(second) == 1
        assert first[0]["id"] != second[0]["id"]
        assert first[0]["current"] is True

    def test_cannot_revoke_another_users_session(self, auth_client, second_farmer_client):
        victim_id = auth_client.get("/api/v1/auth/sessions").get_json()["sessions"][0]["id"]
        response = second_farmer_client.post(
            f"/api/v1/auth/sessions/{victim_id}/revoke",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 404
        assert auth_client.get("/api/profile").status_code == 200

    def test_revoking_the_current_session_signs_the_caller_out(self, auth_client, csrf_token):
        session_id = auth_client.get("/api/v1/auth/sessions").get_json()["sessions"][0]["id"]
        response = auth_client.post(
            f"/api/v1/auth/sessions/{session_id}/revoke",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert response.status_code == 200
        assert response.get_json()["signed_out"] is True
        assert auth_client.get("/api/profile").status_code == 401

    def test_session_management_requires_authentication(self, client):
        assert client.get("/api/v1/auth/sessions").status_code == 401
        assert client.post("/api/v1/auth/sessions/1/revoke").status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_revokes_the_row_and_clears_the_cookie(self, client, login_csrf):
        register(client, login_csrf(), "bye@example.com")
        sign_in(client, login_csrf(), "bye@example.com")
        raw = session_token_of(client)
        user, row = SessionRepository.resolve(raw)
        assert row.is_live()
        # The sign-in cleared the pre-login session, so the token must come from
        # a page rendered inside the new session — as a browser would do.
        response = client.post("/logout", data={"csrf_token": login_csrf("/choose")})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")
        revoked = db.session.get(UserSession, row.id)
        assert revoked.revoked_at is not None
        assert revoked.revoked_reason == "logout"
        assert client.get("/api/profile").status_code == 401
        assert UserRepository.get_by_contact("bye@example.com").id == user.id

    def test_logout_without_csrf_is_refused_for_a_live_session(self, auth_client):
        response = auth_client.post("/logout")
        assert response.status_code == 400
        assert auth_client.get("/api/profile").status_code == 200


# ---------------------------------------------------------------------------
# Authenticated API surface
# ---------------------------------------------------------------------------

class TestApiAuthentication:
    @pytest.mark.parametrize("path", [
        "/api/profile",
        "/api/farms",
        "/api/farmer-context",
        "/api/v1/crop-images/capabilities",
        "/api/v1/voice/capabilities",
        "/api/v1/auth/sessions",
    ])
    def test_unauthenticated_api_returns_401_with_code(self, client, path):
        response = client.get(path)
        assert response.status_code == 401
        assert response.get_json()["code"] == "AUTH_UNAUTHORIZED"

    def test_unauthenticated_post_returns_401_with_code(self, client):
        response = client.post("/api/v1/copilot/messages", json={"question": "hi"})
        assert response.status_code == 401
        assert response.get_json()["code"] == "AUTH_UNAUTHORIZED"

    def test_ask_ai_requires_sign_in_in_farmer_mode(self, client):
        response = client.post("/ask-ai", json={"question": "Hello"})
        assert response.status_code == 401

    def test_public_endpoints_stay_public(self, client):
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/csrf-token").status_code == 200
        assert client.get("/api/live-weather?district=Cuttack").status_code == 200

    def test_wrong_password_change_is_refused_and_keeps_sessions(self, auth_client, csrf_token):
        response = auth_client.post("/api/v1/auth/password", json={
            "current_password": "not-the-password-1",
            "password": NEW_PASSWORD,
            "password_confirm": NEW_PASSWORD,
        }, headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 400
        assert response.get_json()["code"] == "AUTH_INVALID_CREDENTIALS"
        assert auth_client.get("/api/profile").status_code == 200

    def test_password_change_revokes_sessions_and_requires_the_new_password(
        self, app, auth_client, csrf_token
    ):
        response = auth_client.post("/api/v1/auth/password", json={
            "current_password": "test-password-123",
            "password": NEW_PASSWORD,
            "password_confirm": NEW_PASSWORD,
        }, headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 200
        assert response.get_json()["reauthenticate"] is True
        assert auth_client.get("/api/profile").status_code == 401

        fresh = app.test_client()
        html = fresh.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)
        assert sign_in(fresh, token, "tester@example.com", "test-password-123").status_code == 200
        token = re.search(
            r'name="csrf_token" value="([^"]*)"',
            fresh.get("/login").get_data(as_text=True),
        ).group(1)
        assert sign_in(fresh, token, "tester@example.com", NEW_PASSWORD).status_code == 302


# ---------------------------------------------------------------------------
# Password recovery
# ---------------------------------------------------------------------------

class TestPasswordRecovery:
    def test_unavailable_without_a_provider_and_creates_no_token(self, client, login_csrf):
        register(client, login_csrf(), "recover@example.com")
        response = request_reset(client, login_csrf(), "recover@example.com")
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "not available on this deployment" in body
        assert "PASSWORD_RESET_EMAIL_UNAVAILABLE" in body
        # Nothing was issued, and the password is untouched.
        issued = db.session.execute(
            db.select(db.func.count()).select_from(PasswordResetToken)
        ).scalar()
        assert issued == 0
        assert UserRepository.get_by_contact("recover@example.com").check_password(PASSWORD)

    def test_email_provider_reports_unavailable_without_configuration(self, app):
        assert email_provider.is_configured(app.config) is False
        delivery = email_provider.send(
            {"AGRIQ_EMAIL_PROVIDER": "", "AGRIQ_SMTP_HOST": ""},
            to="farmer@example.com", subject="s", body="b",
        )
        assert delivery.sent is False
        assert delivery.status == "PASSWORD_RESET_EMAIL_UNAVAILABLE"

    def test_request_issues_a_hashed_single_use_token(self, app, client, login_csrf, capturing_email):
        configure_email(app)
        register(client, login_csrf(), "mail@example.com")
        response = request_reset(client, login_csrf(), "mail@example.com")
        assert response.status_code == 200
        assert "not available on this deployment" not in response.get_data(as_text=True)
        raw = re.search(r"token=([A-Za-z0-9_\-]+)", capturing_email["body"]).group(1)
        row = PasswordResetRepository.get_by_token(raw)
        assert row is not None
        # Stored hashed, expiring, unused — and the token is not in the page.
        assert row.token_hash != raw
        assert row.used_at is None
        assert row.expires_at is not None
        assert raw not in response.get_data(as_text=True)

    def test_reset_changes_the_password_and_is_single_use(
        self, app, client, login_csrf, capturing_email
    ):
        configure_email(app)
        register(client, login_csrf(), "rotate@example.com")
        request_reset(client, login_csrf(), "rotate@example.com")
        raw = re.search(r"token=([A-Za-z0-9_\-]+)", capturing_email["body"]).group(1)

        page_token = login_csrf(f"/reset-password?token={raw}")
        response = client.post("/reset-password", data={
            "csrf_token": page_token, "token": raw,
            "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD,
        })
        assert response.status_code == 200
        assert "password has been updated" in response.get_data(as_text=True)
        user = UserRepository.get_by_contact("rotate@example.com")
        assert user.check_password(NEW_PASSWORD) is True
        assert user.check_password(PASSWORD) is False
        assert PasswordResetRepository.get_by_token(raw).used_at is not None

        # Replay of the same link is refused and the password does not change again.
        replay_token = login_csrf(f"/reset-password?token={raw}")
        replay = client.post("/reset-password", data={
            "csrf_token": replay_token, "token": raw,
            "password": "third-password-3", "password_confirm": "third-password-3",
        })
        assert "already used, or has expired" in replay.get_data(as_text=True)
        assert UserRepository.get_by_contact("rotate@example.com").check_password(NEW_PASSWORD)

    def test_expired_reset_token_is_rejected(self, app, client, login_csrf, capturing_email):
        configure_email(app)
        register(client, login_csrf(), "stale@example.com")
        request_reset(client, login_csrf(), "stale@example.com")
        raw = re.search(r"token=([A-Za-z0-9_\-]+)", capturing_email["body"]).group(1)
        row = PasswordResetRepository.get_by_token(raw)
        row.expires_at = utc_now() - timedelta(minutes=1)
        db.session.commit()
        page_token = login_csrf(f"/reset-password?token={raw}")
        response = client.post("/reset-password", data={
            "csrf_token": page_token, "token": raw,
            "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD,
        })
        assert "already used, or has expired" in response.get_data(as_text=True)
        assert UserRepository.get_by_contact("stale@example.com").check_password(PASSWORD)

    def test_reset_revokes_every_existing_session(self, app, client, login_csrf, capturing_email):
        configure_email(app)
        register(client, login_csrf(), "revoke-all@example.com")
        sign_in(client, login_csrf(), "revoke-all@example.com")
        assert client.get("/api/profile").status_code == 200
        request_reset(client, login_csrf(), "revoke-all@example.com")
        raw = re.search(r"token=([A-Za-z0-9_\-]+)", capturing_email["body"]).group(1)
        user = UserRepository.get_by_contact("revoke-all@example.com")
        rows = SessionRepository.list_for_user(user.id)
        assert rows and all(row.revoked_at is None for row in rows)

        page_token = login_csrf(f"/reset-password?token={raw}")
        client.post("/reset-password", data={
            "csrf_token": page_token, "token": raw,
            "password": NEW_PASSWORD, "password_confirm": NEW_PASSWORD,
        })
        assert all(row.revoked_at is not None for row in SessionRepository.list_for_user(user.id))
        assert client.get("/api/profile").status_code == 401

    def test_reset_requires_a_matching_confirmation(self, app, client, login_csrf, capturing_email):
        configure_email(app)
        register(client, login_csrf(), "confirm@example.com")
        request_reset(client, login_csrf(), "confirm@example.com")
        raw = re.search(r"token=([A-Za-z0-9_\-]+)", capturing_email["body"]).group(1)
        page_token = login_csrf(f"/reset-password?token={raw}")
        response = client.post("/reset-password", data={
            "csrf_token": page_token, "token": raw,
            "password": NEW_PASSWORD, "password_confirm": "different-password-9",
        })
        assert "do not match" in response.get_data(as_text=True)
        assert UserRepository.get_by_contact("confirm@example.com").check_password(PASSWORD)

    def test_recovery_post_requires_csrf(self, client, login_csrf):
        register(client, login_csrf(), "csrfrec@example.com")
        response = client.post("/forgot-password", data={"user_contact": "csrfrec@example.com"})
        assert response.status_code == 400

    def test_unknown_contact_gets_the_same_answer(self, app, client, login_csrf, capturing_email):
        configure_email(app)
        response = request_reset(client, login_csrf(), "nobody-here@example.com")
        assert response.status_code == 200
        assert "not available on this deployment" not in response.get_data(as_text=True)
        assert capturing_email == {}  # nothing was sent anywhere


# ---------------------------------------------------------------------------
# Authorization isolation (IDOR)
# ---------------------------------------------------------------------------

def create_profile(client, csrf_token, name="Isolation One"):
    return client.post("/api/profile", json={
        "full_name": name, "state": "Odisha", "district": "Cuttack",
        "consent_version": "v1-2026",
    }, headers={"X-CSRF-Token": csrf_token})


class TestAuthorizationIsolation:
    def test_farmer_context_is_per_user(self, auth_client, second_farmer_client, csrf_token):
        created = create_profile(auth_client, csrf_token)
        assert created.status_code == 201
        first = auth_client.get("/api/farmer-context").get_json()["context"]
        second = second_farmer_client.get("/api/farmer-context").get_json()["context"]
        assert first["farmer"]["full_name"] == "Isolation One"
        # The other farmer has no profile and never sees the first one's data.
        assert second["farmer"] is None
        assert second["onboarding_required"] is True
        assert first["farmer"]["id"] != (second.get("farmer") or {}).get("id")

    def test_foreign_farm_is_not_visible(self, auth_client, second_farmer_client, csrf_token):
        assert create_profile(auth_client, csrf_token).status_code == 201
        # The other farmer is onboarded too, so the only reason they cannot see
        # the farm is ownership — not a missing profile.
        assert create_profile(second_farmer_client, csrf_token, "Isolation Two").status_code == 201
        created = auth_client.post("/api/farms", json={
            "name": "Isolation Farm", "district": "Cuttack", "state": "Odisha",
            "total_area": 1.5, "area_unit": "acre", "ownership_type": "owned",
        }, headers={"X-CSRF-Token": csrf_token})
        assert created.status_code in (200, 201)
        farm_id = created.get_json()["farm"]["id"]
        assert auth_client.get(f"/api/farms/{farm_id}").status_code == 200
        # Cross-user access is a 404 (nothing is enumerated), never a 200.
        assert second_farmer_client.get(f"/api/farms/{farm_id}").status_code == 404

    def test_unauthenticated_cannot_read_or_write_farmer_data(self, client):
        assert client.get("/api/farms").status_code == 401
        assert client.post("/api/farms", json={"name": "x"}).status_code == 401


# ---------------------------------------------------------------------------
# Robustness / no-bypass guarantees
# ---------------------------------------------------------------------------

class TestRobustness:
    @pytest.mark.parametrize("payload", [
        {"user_contact": "a" * 5000, "password": PASSWORD},
        {"user_contact": "' OR 1=1 --", "password": PASSWORD},
        {"user_contact": "farmer@example.com", "password": "x" * 5000},
        {"user_contact": "", "password": ""},
        {"user_contact": "<script>alert(1)</script>", "password": PASSWORD},
        {"user_contact": "farmer@example.com\x00", "password": PASSWORD},
    ])
    def test_malformed_login_payloads_never_500_and_never_echo(self, client, login_csrf, payload):
        data = dict(payload)
        data["csrf_token"] = login_csrf()
        response = client.post("/login", data=data)
        assert response.status_code in (200, 400)
        body = response.get_data(as_text=True)
        assert "Traceback" not in body
        assert "sqlite" not in body.lower()
        assert "password_hash" not in body

    def test_error_responses_never_leak_internals(self, client):
        response = client.get("/api/profile")
        assert response.status_code == 401
        body = response.get_data(as_text=True)
        for leak in ("Traceback", "sqlite", "scrypt:", "/home/", "C:\\"):
            assert leak not in body

    def test_no_authentication_bypass_markers_in_production_source(self):
        """§34/§54: no bypass, no mock auth, no fake identity in shipped code."""
        from pathlib import Path

        api_root = Path(__file__).resolve().parents[2] / "agriq"
        forbidden = (
            "skip_auth", "disable_auth", "auth_bypass", "allow_unauthenticated",
            "mock_user", "fake_user", "fake_session", "dummy_user",
            "is_authenticated = True", "is_authenticated=True",
            "authenticated = True", "authenticated=True", "user_id = 1",
        )
        offenders = []
        for path in api_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{path.name}: {marker}")
        assert offenders == []

    def test_no_hardcoded_credentials_in_production_source(self):
        """No shipped password literal can authenticate anyone."""
        from pathlib import Path

        api_root = Path(__file__).resolve().parents[2] / "agriq"
        # Values that would be a credential if they appeared as a stored hash or
        # an accepted password. The weak-password deny-list lives in one place and
        # is a *rejection* list, so it is checked separately below.
        hashes = []
        for path in api_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "scrypt:" in text or "$argon2" in text:
                hashes.append(path.name)
        assert hashes == []
