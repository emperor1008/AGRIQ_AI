"""Shared pytest fixtures for AGRIQ AI tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq import create_app  # noqa: E402
from agriq.core.config import TestingConfig  # noqa: E402
from agriq.core.constants import (  # noqa: E402
    SESSION_ID_KEY,
    SESSION_MODE_KEY,
    SESSION_TOKEN_KEY,
    SESSION_USER_KEY,
)
from agriq.extensions import db as _db  # noqa: E402
from agriq.repositories.session_repository import SessionRepository  # noqa: E402
from agriq.repositories.user_repository import UserRepository  # noqa: E402

TEST_PASSWORD = "test-password-123"


@pytest.fixture()
def app():
    """Fresh app instance with a clean in-memory database per test."""
    application = create_app(TestingConfig())
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
    )
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def csrf_token():
    return "test-csrf-token"


@pytest.fixture()
def login_csrf(client):
    """Read the CSRF token a browser would receive with the login form.

    Phase 7.1 validates the login POST's CSRF token whenever the session already
    carries a nonce, so tests must load the page first — exactly like a browser.
    """
    import re

    def _token(path: str = "/login") -> str:
        html = client.get(path).get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]*)"', html)
        return match.group(1) if match else ""

    return _token


def _ensure_user(contact: str):
    """Create a real (test-fixture) user row for session-backed flows."""
    user = UserRepository.get_by_contact(contact)
    if user is None:
        user = UserRepository.create(contact, TEST_PASSWORD)
    return user


def start_session(client, contact: str, mode: str, csrf_token: str):
    """Sign a test client in through the *real* session machinery.

    Phase 7.1: fixtures must not forge a cookie that production would reject.
    A genuine ``user_sessions`` row is created via the repository, exactly as
    ``POST /login`` does, and the cookie carries its opaque token.
    """
    user = _ensure_user(contact)
    row, raw_token = SessionRepository.create(
        user, idle_timeout_hours=8, absolute_timeout_hours=24 * 30
    )
    with client.session_transaction() as session:
        session["_agriq_csrf_token"] = csrf_token
        session[SESSION_USER_KEY] = contact
        session[SESSION_MODE_KEY] = mode
        session[SESSION_TOKEN_KEY] = raw_token
        session[SESSION_ID_KEY] = row.id
    return user


@pytest.fixture()
def auth_client(client, csrf_token):
    """Client with an authenticated farmer session backed by real rows."""
    start_session(client, "tester@example.com", "farmer", csrf_token)
    return client


@pytest.fixture()
def student_client(client, csrf_token):
    """Client with an authenticated student session backed by real rows."""
    start_session(client, "student@example.com", "student", csrf_token)
    return client


@pytest.fixture()
def second_farmer_client(app, csrf_token):
    """A second INDEPENDENT farmer session (own cookie jar) for
    ownership-isolation tests — sharing one client would merge sessions."""
    own_client = app.test_client()
    start_session(own_client, "other-farmer@example.com", "farmer", csrf_token)
    return own_client
