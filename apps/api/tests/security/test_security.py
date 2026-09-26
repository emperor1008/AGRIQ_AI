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
    """Strengthened in Phase 7 (finding F-05).

    The original guard asserted that the curated band was *labelled* as a band.
    Phase 7 went further and removed the unsourced band entirely: this module
    must now produce NO rupee figure at all, and must say so explicitly. Rupee
    values may only ever come from the AGMARKNET provider through
    services/market_service.
    """
    import json

    from agriq.services.farm_intelligence import market_advisory, profit_impact

    advisory = market_advisory("rice", "Cuttack", 50, 80)
    assert advisory["available"] is False
    assert advisory["status"] == "DATA_UNAVAILABLE"
    assert advisory["range"] is None
    assert advisory["pressure"] is None
    assert advisory["message"]
    assert "₹" not in json.dumps(advisory)

    # Every previously-served band entry, plus a crop that was never in the old
    # table (the invented (1200, 3200) fallback case), must yield no number.
    for crop_key in ("rice", "tomato", "sugarcane", "watermelon", "dragonfruit"):
        assert "₹" not in json.dumps(market_advisory(crop_key, "Cuttack", 50, 80))
        assert "₹" not in profit_impact(50, crop_key)


def test_curated_price_table_is_gone(auth_client):
    """Phase 7 F-05: the unsourced MARKET_BASELINE table was deleted outright."""
    import agriq.domain.catalogs.crops as crops

    assert not hasattr(crops, "MARKET_BASELINE")


def test_dashboard_offers_no_fabricated_demo_submit(auth_client):
    """Phase 7 F-02: no production control may auto-submit fabricated context.

    `runDemoCase()` filled crop/district/growth-stage/field-condition with
    values the farmer never entered and submitted the real analysis form, so
    fabricated observations were persisted as farmer-reported data. Both the
    control and its handler must stay gone.
    """
    html = auth_client.get("/dashboard").get_data(as_text=True)
    assert "Run Demo Case" not in html
    assert "runDemoCase" not in html

    for module in ("leafscan", "app"):
        js = auth_client.get(f"/static/js/{module}.js").get_data(as_text=True)
        assert "runDemoCase" not in js, f"{module}.js still defines runDemoCase"

    leafscan_js = auth_client.get("/static/js/leafscan.js").get_data(as_text=True)
    assert ".submit()" not in leafscan_js


def test_dashboard_does_not_render_rupee_estimates(auth_client, csrf_token):
    """Phase 7 F-05/F-06: no rupee figure without a verified source.

    The impact card used to print "₹X - ₹Y / acre if untreated" (curated price
    band x risk score) and a "Mandi band (context, not live)" rupee row.
    """
    response = auth_client.post(
        "/dashboard",
        data={
            "crop": "Rice", "district": "Cuttack",
            "growth_stage": "Vegetative", "field_condition": "Normal field",
            "csrf_token": csrf_token,
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "per acre" not in html
    assert "/ quintal" not in html
    assert "Mandi band" not in html
    assert "Rule estimate" in html
    assert "Indicative bands" in html


def test_legacy_confidence_is_labelled_uncalibrated(auth_client, csrf_token):
    """Phase 7 F-03/F-04: heuristic numbers ship with their honest status."""
    from agriq.domain.risk.scoring import (
        confidence_score, confidence_status, heuristic_status, yield_loss_status,
    )

    assert confidence_status() == "CONFIDENCE_NOT_CALIBRATED"
    assert yield_loss_status() == "YIELD_IMPACT_NOT_MEASURED"
    assert heuristic_status() == "HEURISTIC_NOT_VALIDATED"
    # The screening band itself is unchanged; only its label is now truthful.
    assert 40 <= confidence_score(70, {"available": True}, {"available": False}, {"x": 20}) <= 94


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
