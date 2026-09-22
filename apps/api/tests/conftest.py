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
from agriq.extensions import db as _db  # noqa: E402
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


def _ensure_user(contact: str):
    """Create a real (test-fixture) user row for session-backed flows."""
    user = UserRepository.get_by_contact(contact)
    if user is None:
        user = UserRepository.create(contact, TEST_PASSWORD)
    return user


@pytest.fixture()
def auth_client(client, csrf_token):
    """Client with an authenticated farmer session backed by a real user row."""
    contact = "tester@example.com"
    _ensure_user(contact)
    with client.session_transaction() as session:
        session["_agriq_csrf_token"] = csrf_token
        session["user_contact"] = contact
        session["user_mode"] = "farmer"
    return client


@pytest.fixture()
def student_client(client, csrf_token):
    """Client with an authenticated student session backed by a real user row."""
    contact = "student@example.com"
    _ensure_user(contact)
    with client.session_transaction() as session:
        session["_agriq_csrf_token"] = csrf_token
        session["user_contact"] = contact
        session["user_mode"] = "student"
    return client


@pytest.fixture()
def second_farmer_client(app, csrf_token):
    """A second INDEPENDENT farmer session (own cookie jar) for
    ownership-isolation tests — sharing one client would merge sessions."""
    contact = "other-farmer@example.com"
    _ensure_user(contact)
    own_client = app.test_client()
    with own_client.session_transaction() as session:
        session["_agriq_csrf_token"] = csrf_token
        session["user_contact"] = contact
        session["user_mode"] = "farmer"
    return own_client
