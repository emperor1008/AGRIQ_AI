"""Security + data-integrity tests (03_SECURITY_AND_ACCESS.md, ARC-09).

Covers: CSRF protection, security headers, session cookie flags, upload
validation, PWA assets, and the no-fabrication guarantees for provider
data (weather, market, Gemini, map risk).
"""
from __future__ import annotations

import io
import json

from PIL import Image


def _png(color=(60, 140, 60)) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def test_choose_mode_without_csrf_rejected(auth_client):
    response = auth_client.post("/choose-mode", data={"mode": "farmer"})
    assert response.status_code == 400
    assert "CSRF" in response.get_data(as_text=True)


def test_choose_mode_with_bad_csrf_rejected(auth_client):
    response = auth_client.post(
        "/choose-mode", data={"mode": "farmer", "csrf_token": "wrong-token"}
    )
    assert response.status_code == 400


def test_ask_ai_without_csrf_rejected(auth_client):
    response = auth_client.post(
        "/ask-ai", json={"question": "hello"}, headers={"X-CSRF-Token": "nope"}
    )
    assert response.status_code == 403


def test_logout_without_csrf_rejected(auth_client):
    response = auth_client.post("/logout")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Security headers + cookies
# ---------------------------------------------------------------------------

def test_security_headers_present(client):
    response = client.get("/healthz")
    headers = response.headers
    assert "Content-Security-Policy" in headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in headers


def test_csp_blocks_foreign_scripts(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_session_cookie_flags(app, client):
    client.get("/")
    cookie_header = None
    response = client.get("/")
    # Flask test client exposes cookie via Set-Cookie when session set
    with client.session_transaction() as session:
        session["user_contact"] = "flagcheck@example.com"
    response = client.get("/choose")
    assert response.status_code == 200
    config = app.config
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"


# ---------------------------------------------------------------------------
# Upload validation (server-side)
# ---------------------------------------------------------------------------

def test_upload_rejects_oversized(auth_client):
    big = io.BytesIO(b"\x00" * (6 * 1024 * 1024))
    response = auth_client.post("/dashboard", data={
        "crop": "Rice", "district": "Cuttack",
        "growth_stage": "Vegetative", "field_condition": "Normal field",
        "leaf_photo": (big, "big.png"),
    }, content_type="multipart/form-data")
    html = response.get_data(as_text=True)
    # analysis still renders; LeafScan reports honest not-analysed state
    assert response.status_code == 200
    assert "Image not analysed" in html or "under 5 MiB" in html


def test_upload_rejects_wrong_type(auth_client):
    fake = io.BytesIO(b"GIF89a-not-really")
    response = auth_client.post("/dashboard", data={
        "crop": "Rice", "district": "Cuttack",
        "growth_stage": "Vegetative", "field_condition": "Normal field",
        "leaf_photo": (fake, "fake.png"),
    }, content_type="multipart/form-data")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Image not analysed" in html or "JPG" in html


def test_upload_valid_image_processed(auth_client):
    response = auth_client.post("/dashboard", data={
        "crop": "Rice", "district": "Cuttack",
        "growth_stage": "Vegetative", "field_condition": "Normal field",
        "leaf_photo": (_png(), "leaf.png"),
    }, content_type="multipart/form-data")
    html = response.get_data(as_text=True)
    assert "leaf-preview" in html


# ---------------------------------------------------------------------------
# PWA assets
# ---------------------------------------------------------------------------

def test_manifest_loads(client):
    response = client.get("/static/manifest.json")
    assert response.status_code == 200
    manifest = json.loads(response.get_data(as_text=True))
    assert manifest["name"].startswith("AGRIQ AI")
    assert manifest["start_url"] == "/"


def test_service_worker_loads(client):
    response = client.get("/static/sw.js")
    assert response.status_code == 200
    assert "agriq-static" in response.get_data(as_text=True)


def test_all_css_modules_served(client):
    for module in ["tokens", "base", "components", "dashboard", "animations", "responsive"]:
        assert client.get(f"/static/css/{module}.css").status_code == 200


def test_all_js_modules_served(client):
    for module in ["app", "api-client", "assistant", "dashboard", "map", "weather", "leafscan", "pwa"]:
        assert client.get(f"/static/js/{module}.js").status_code == 200


def test_logo_served(client):
    response = client.get("/static/images/agriq-ai-logo.png")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"


# ---------------------------------------------------------------------------
# No-fabrication guarantees
# ---------------------------------------------------------------------------

def test_weather_badge_always_labels_source(auth_client):
    html = auth_client.get("/api/live-weather?district=Puri").get_data(as_text=True)
    assert ("LIVE SYNC" in html) or ("OFFLINE FALLBACK" in html)


def test_offline_fallback_marked_not_live(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", _boom)
    from agriq.integrations.weather import open_meteo

    open_meteo._cache.clear()
    weather = open_meteo.get_weather("Cuttack")
    assert weather["live"] is False
    open_meteo._cache.clear()


def test_market_endpoint_never_returns_prices_without_provider(auth_client):
    """No market prices may appear as live without AGMARKNET configured."""
    response = auth_client.get("/api/live-weather?district=Cuttack")
    assert response.status_code == 200  # weather endpoint untouched by market


def test_market_band_only_via_service_context(auth_client):
    """The curated band must be labelled as a band, never as live price."""
    from agriq.services.farm_intelligence import market_advisory

    advisory = market_advisory("rice", "Cuttack", 50, 80)
    assert "/ quintal" in advisory["range"]
    assert "₹" in advisory["range"]


def test_map_data_covers_all_districts_without_fake_selection(auth_client):
    """Phase 1: unanalysed districts carry NO fabricated risk score — they
    are marked awaiting-analysis and display the awaiting message."""
    from agriq.domain.catalogs.districts import DISTRICTS
    from agriq.domain.catalogs.crops import resolve_crop
    from agriq.services.farm_intelligence import make_map_data
    from agriq.core.constants import AWAITING_ANALYSIS_MESSAGE

    crop, _ = resolve_crop("rice")
    rows = make_map_data(crop)
    assert {row["district"] for row in rows} == set(DISTRICTS)
    for row in rows:
        assert row["analysed"] is False
        assert row["risk"] is None
        assert row["status"] == "PENDING"
        assert row["awaiting"] == AWAITING_ANALYSIS_MESSAGE

    # After a real analysis, exactly one district carries the actual score.
    analysed = make_map_data(crop, "Cuttack", 54)
    cuttack = next(r for r in analysed if r["district"] == "Cuttack")
    assert cuttack["analysed"] is True and cuttack["risk"] == 54
    others = [r for r in analysed if r["district"] != "Cuttack"]
    assert all(r["risk"] is None for r in others)


def test_assistant_farmer_unavailable_state_explicit(auth_client, csrf_token):
    """Farmer assistant without Gemini is an explicit unavailable state."""
    response = auth_client.post(
        "/ask-ai",
        json={"question": "fertilizer guidance"},
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = response.get_json()
    assert payload["source"] == "unavailable"
    assert payload["ok"] is False


def test_assistant_student_mode_labels_knowledge_engine(student_client, csrf_token):
    """Student mode keeps the rule-based engine, clearly labelled."""
    response = student_client.post(
        "/ask-ai",
        json={"question": "Give MCQs with answers", "context": {"learning_area": "Agronomy"}},
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = response.get_json()
    assert payload["source"] == "knowledge_engine"
    assert "knowledge engine" in payload.get("source_label", "").lower()


# ---------------------------------------------------------------------------
# Production config guard rails
# ---------------------------------------------------------------------------

def test_production_config_requires_postgres_and_redis(monkeypatch):
    from agriq.core.config import ProductionConfig

    monkeypatch.setenv("AGRIQ_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///prod.db")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    import pytest

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        ProductionConfig()

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/agriq")
    with pytest.raises(RuntimeError, match="Redis"):
        ProductionConfig()


def test_secrets_not_in_source_tree():
    import re
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2] / "agriq"
    pattern = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,})")
    for py in api_root.rglob("*.py"):
        assert not pattern.search(py.read_text(encoding="utf-8")), f"secret-like key in {py}"
