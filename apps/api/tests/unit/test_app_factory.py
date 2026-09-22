"""Application factory + health endpoint tests (ARC-01, ARC-09)."""
from __future__ import annotations

from agriq import create_app
from agriq.core.config import TestingConfig


def test_create_app_returns_configured_flask_app():
    app = create_app(TestingConfig())
    assert app.name == "agriq"
    assert app.config["TESTING"] is True


def test_all_legacy_routes_registered():
    app = create_app(TestingConfig())
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    for expected in [
        "/",
        "/login",
        "/choose",
        "/choose-mode",
        "/dashboard",
        "/ask-ai",
        "/api/live-weather",
        "/logout",
        "/healthz",
    ]:
        assert expected in rules, f"missing legacy route {expected}"


def test_healthz_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["service"] == "agriq-ai"


def test_healthz_does_not_call_providers(client, monkeypatch):
    """Health check must stay dependency-free."""
    import requests

    def _boom(*args, **kwargs):  # pragma: no cover
        raise AssertionError("healthz must not perform HTTP calls")

    monkeypatch.setattr(requests, "get", _boom)
    assert client.get("/healthz").status_code == 200
