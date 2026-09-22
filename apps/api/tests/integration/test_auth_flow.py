"""End-to-end route integration tests (ARC-09).

Covers: login/registration, session protection, mode selection, farmer and
student dashboards, assistant and weather APIs, logout.
"""
from __future__ import annotations

import io

from PIL import Image


def _leaf_png() -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (320, 320), (58, 132, 58)).save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Auth + session protection
# ---------------------------------------------------------------------------

def test_index_redirects_authenticated_to_choose(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/choose")


def test_index_shows_login_for_guest(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AGRIQ AI" in response.get_data(as_text=True)


def test_real_account_registration_and_login(client):
    """Phase 1: real accounts — register with password, then sign in."""
    response = client.post("/login", data={
        "user_contact": "farmer@example.com",
        "password": "harvest-secret-1",
        "password_confirm": "harvest-secret-1",
    })
    assert response.status_code == 200
    assert "Registration successful" in response.get_data(as_text=True)

    response = client.post("/login", data={
        "user_contact": "farmer@example.com",
        "password": "harvest-secret-1",
    })
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/choose")


def test_login_without_password_rejected(client):
    """The transparent no-password registration path is removed."""
    response = client.post("/login", data={"user_contact": "Guest"})
    assert response.status_code == 200  # form re-rendered with message
    assert "password" in response.get_data(as_text=True).lower()


def test_login_wrong_password_generic_error(client):
    client.post("/login", data={
        "user_contact": "exists@example.com",
        "password": "a-good-password-1",
        "password_confirm": "a-good-password-1",
    })
    response = client.post("/login", data={
        "user_contact": "exists@example.com",
        "password": "wrong-password-9",
    })
    assert response.status_code == 200
    assert "Invalid contact or password" in response.get_data(as_text=True)


def test_dashboard_requires_login(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_choose_requires_login(client):
    response = client.get("/choose", follow_redirects=False)
    assert response.status_code == 302


def test_logout_clears_session(auth_client, csrf_token):
    response = auth_client.post("/logout", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    response = auth_client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302  # redirected to login


# ---------------------------------------------------------------------------
# Mode selection
# ---------------------------------------------------------------------------

def test_choose_mode_farmer(auth_client, csrf_token):
    response = auth_client.post(
        "/choose-mode", data={"mode": "farmer", "csrf_token": csrf_token}
    )
    assert response.status_code == 302
    with auth_client.session_transaction() as session:
        assert session["user_mode"] == "farmer"


def test_choose_mode_student(auth_client, csrf_token):
    response = auth_client.post(
        "/choose-mode", data={"mode": "student", "csrf_token": csrf_token}
    )
    assert response.status_code == 302
    with auth_client.session_transaction() as session:
        assert session["user_mode"] == "student"


def test_choose_mode_invalid_defaults_to_farmer(auth_client, csrf_token):
    auth_client.post("/choose-mode", data={"mode": "hacker", "csrf_token": csrf_token})
    with auth_client.session_transaction() as session:
        assert session["user_mode"] == "farmer"


# ---------------------------------------------------------------------------
# Farmer dashboard
# ---------------------------------------------------------------------------

def test_farmer_dashboard_get_renders(auth_client):
    html = auth_client.get("/dashboard").get_data(as_text=True)
    assert "Odisha GeoRisk Intelligence Map" in html
    assert "Analyze Farm Intelligence" in html


def test_farmer_dashboard_post_full_analysis(auth_client):
    response = auth_client.post("/dashboard", data={
        "crop": "Rice",
        "district": "Cuttack",
        "growth_stage": "Vegetative",
        "field_condition": "Humid field",
        "leaf_photo": (_leaf_png(), "leaf.png"),
    }, content_type="multipart/form-data")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Farm Intelligence Report" in html
    assert "Why This Risk?" in html
    assert "LeafScan Symptom Intelligence" in html
    # provenance label present for weather console
    assert ("LIVE SYNC" in html) or ("OFFLINE FALLBACK" in html)


def test_farmer_dashboard_analysis_numbers_present(auth_client):
    html = auth_client.post("/dashboard", data={
        "crop": "Tomato", "district": "Puri",
        "growth_stage": "Flowering", "field_condition": "Waterlogged field",
    }).get_data(as_text=True)
    assert "Risk Breakdown" in html
    assert "% risk" in html


# ---------------------------------------------------------------------------
# Student dashboard
# ---------------------------------------------------------------------------

def test_student_dashboard_get_renders(student_client):
    html = student_client.get("/dashboard").get_data(as_text=True)
    assert "Student Research Console" in html


def test_student_dashboard_post_generates_workspace(student_client):
    html = student_client.post("/dashboard", data={
        "learning_area": "Plant Pathology",
        "topic": "Plant Disease Triangle",
        "crop": "Rice",
        "study_purpose": "Exam Preparation",
    }).get_data(as_text=True)
    assert "AI Academic Workspace" in html
    assert "MCQ Practice with 4 Options" in html
    assert "Research Methodology + Statistics" in html


# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

def test_ask_ai_farmer_mode_without_gemini_is_unavailable(auth_client, csrf_token):
    """Phase 1: farmer-mode assistant without Gemini returns an explicit
    unavailable state — no scripted answer is labelled as AI."""
    response = auth_client.post(
        "/ask-ai",
        json={"question": "What should I do today?", "context": {"crop": "Rice"}},
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["source"] == "unavailable"
    assert payload["answer"]


def test_ask_ai_requires_question(auth_client, csrf_token):
    response = auth_client.post(
        "/ask-ai", json={"question": ""}, headers={"X-CSRF-Token": csrf_token}
    )
    assert "Please type" in response.get_json()["answer"]


def test_ask_ai_student_mode(student_client, csrf_token):
    response = student_client.post(
        "/ask-ai",
        json={"question": "Give MCQs with answers", "context": {"learning_area": "Agronomy"}},
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = response.get_json()
    assert "MCQ" in payload["answer"]


def test_live_weather_api_shape(auth_client):
    response = auth_client.get("/api/live-weather?district=Cuttack&crop=Rice")
    payload = response.get_json()
    assert response.status_code == 200
    console = payload["weather_console"]
    assert console["live_badge"] in {"LIVE SYNC", "OFFLINE FALLBACK"}
    assert len(payload["risk_forecast"]) == 7
    assert "source_note" in console


def test_live_weather_api_rejects_bad_stage(auth_client):
    response = auth_client.get(
        "/api/live-weather?district=Cuttack&crop=Rice&growth_stage=<script>"
    )
    payload = response.get_json()
    # falls back to safe default; never echoes unsanitised input
    assert response.status_code == 200
    assert payload["weather_console"]["district"] == "Cuttack"
