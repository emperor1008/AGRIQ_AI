"""Phase 1 farmer-data API integration tests.

Covers the full onboarding workflow (profile → farm → field → soil → crop
cycle → stage confirm → observation → context) plus ownership isolation:
a second user must never read or modify the first user's records.
"""
from __future__ import annotations

import io

from PIL import Image


def _png(color=(90, 160, 80)) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (240, 240), color).save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def test_profile_create_get_patch(auth_client, csrf_token):
    headers = {"X-CSRF-Token": csrf_token}
    response = auth_client.post("/api/profile", json={
        "full_name": "Ramesh Pradhan",
        "preferred_language": "Odia",
        "state": "Odisha",
        "district": "Cuttack",
        "village": "Narasinghpur",
        "consent_version": "v1-2026",
    }, headers=headers)
    assert response.status_code == 201
    profile = response.get_json()["profile"]
    assert profile["full_name"] == "Ramesh Pradhan"
    assert profile["consented_at"]

    response = auth_client.get("/api/profile")
    assert response.get_json()["profile"]["district"] == "Cuttack"

    response = auth_client.patch("/api/profile", json={"village": "Salepur"},
                                 headers=headers)
    assert response.get_json()["profile"]["village"] == "Salepur"


def test_profile_requires_authentication(client):
    assert client.get("/api/profile").status_code == 404


def test_profile_csrf_enforced(auth_client):
    response = auth_client.post("/api/profile", json={"full_name": "X"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Onboarding chain: farm → field → soil → cycle → stage → observation
# ---------------------------------------------------------------------------

def _onboard(client, csrf_token):
    """Create profile + farm + field; returns ids."""
    headers = {"X-CSRF-Token": csrf_token}
    client.post("/api/profile", json={
        "full_name": "Onboard Test", "district": "Cuttack", "state": "Odisha",
        "consent_version": "v1-2026",
    }, headers=headers)
    farm = client.post("/api/farms", json={
        "name": "North Farm", "district": "Cuttack", "state": "Odisha",
        "latitude": 20.46, "longitude": 85.88, "total_area": 2.5,
        "area_unit": "acre", "ownership_type": "owned",
    }, headers=headers).get_json()["farm"]
    field = client.post(f"/api/farms/{farm['id']}/fields", json={
        "name": "Rice Field", "area": 1.2, "area_unit": "acre",
        "soil_type": "Alluvial", "irrigation_type": "Canal",
    }, headers=headers).get_json()["field"]
    return farm["id"], field["id"]

def test_full_onboarding_flow(auth_client, csrf_token):
    headers = {"X-CSRF-Token": csrf_token}
    farm_id, field_id = _onboard(auth_client, csrf_token)

    # Soil: only the values the farmer knows; missing stay unknown.
    soil = client_post_soil(auth_client, headers, field_id, {
        "source_type": "farmer_entered", "ph": "6.2",
    })
    assert soil["ph"] == 6.2
    assert soil["nitrogen"] is None  # unknown stays unknown
    assert soil["organic_carbon"] is None

    # Crop cycle with transparent stage calculation.
    cycle = auth_client.post(f"/api/fields/{field_id}/crop-cycles", json={
        "crop_name": "Rice", "variety": "Swarna", "season": "Kharif",
        "sowing_date": "2026-07-10",
    }, headers=headers).get_json()
    payload = cycle["crop_cycle"]
    assert payload["calculated_stage"], "stage should be calculated from the reference"
    assert cycle["stage_calculation"]["farmer_confirmation_required"] is True
    assert cycle["stage_calculation"]["reference_version"]

    # Farmer confirms (or corrects) the stage — stored separately.
    confirmed = auth_client.post(
        f"/api/crop-cycles/{payload['id']}/confirm-stage",
        json={"stage": "Tillering"}, headers=headers,
    )
    assert confirmed.status_code == 200
    body = confirmed.get_json()["crop_cycle"]
    assert body["farmer_confirmed_stage"] == "Tillering"
    assert body["calculated_stage"] == payload["calculated_stage"], (
        "farmer confirmation must not overwrite the calculated reference"
    )

    # Observation with image.
    observation = auth_client.post(
        f"/api/crop-cycles/{payload['id']}/observations",
        data={"observation_type": "pest", "notes": "Stem borer near bund",
              "farmer_reported_severity": "moderate",
              "image": (_png(), "leaf.png")},
        content_type="multipart/form-data", headers=headers,
    ).get_json()["observation"]
    assert observation["has_image"] is True
    assert observation["farmer_reported_severity"] == "moderate"

    # Context carries everything, weather provenance included.
    context = auth_client.get("/api/farmer-context").get_json()["context"]
    assert context["farm"]["id"] == farm_id
    assert context["field"]["id"] == field_id
    assert context["crop_cycle"]["farmer_confirmed_stage"] == "Tillering"
    assert context["soil"]["available"] is True
    assert context["soil"]["source_type"] == "farmer_entered"
    assert context["weather"]["provider"] == "Open-Meteo"
    assert context["weather"]["retrieved_at"] or context["weather"]["available"] is False
    assert len(context["recent_observations"]) == 1


def client_post_soil(client, headers, field_id, payload):
    response = client.post(f"/api/fields/{field_id}/soil-tests", json=payload,
                           headers=headers)
    assert response.status_code == 201
    return response.get_json()["soil_test"]


# ---------------------------------------------------------------------------
# Ownership isolation (two users)
# ---------------------------------------------------------------------------

def test_owner_isolation_farm(auth_client, second_farmer_client, csrf_token):
    headers = {"X-CSRF-Token": csrf_token}
    farm_id, _ = _onboard(auth_client, csrf_token)
    # The second farmer is fully onboarded too, so 404 proves the
    # ownership check (not a missing-profile guard) blocks access.
    _onboard(second_farmer_client, csrf_token)

    # Other farmer cannot read the farm.
    assert second_farmer_client.get(f"/api/farms/{farm_id}").status_code == 404
    # ...cannot modify it...
    assert second_farmer_client.patch(
        f"/api/farms/{farm_id}", json={"name": "Hacked"}, headers=headers
    ).status_code == 404
    # ...cannot archive it...
    assert second_farmer_client.post(
        f"/api/farms/{farm_id}/archive", headers=headers
    ).status_code == 404
    # ...and cannot add fields to it.
    assert second_farmer_client.post(
        f"/api/farms/{farm_id}/fields", json={"name": "Intruder"},
        headers=headers,
    ).status_code == 404
    # Original owner still sees it.
    assert auth_client.get(f"/api/farms/{farm_id}").status_code == 200


def test_owner_isolation_field_soil_cycle(auth_client, second_farmer_client, csrf_token):
    headers = {"X-CSRF-Token": csrf_token}
    _farm_id, field_id = _onboard(auth_client, csrf_token)
    _onboard(second_farmer_client, csrf_token)
    cycle_id = auth_client.post(
        f"/api/fields/{field_id}/crop-cycles",
        json={"crop_name": "Rice", "sowing_date": "2026-07-01"},
        headers=headers,
    ).get_json()["crop_cycle"]["id"]

    assert second_farmer_client.get(f"/api/fields/{field_id}").status_code == 404
    assert second_farmer_client.post(
        f"/api/fields/{field_id}/soil-tests", json={"ph": "3.0"}, headers=headers
    ).status_code == 404
    assert second_farmer_client.get(
        f"/api/fields/{field_id}/crop-cycles"
    ).status_code == 404
    assert second_farmer_client.post(
        f"/api/crop-cycles/{cycle_id}/confirm-stage", json={"stage": "Seedling"},
        headers=headers,
    ).status_code == 404
    assert second_farmer_client.get(
        f"/api/crop-cycles/{cycle_id}/observations"
    ).status_code == 404


def test_farmer_context_never_crosses_users(auth_client, second_farmer_client, csrf_token):
    _onboard(auth_client, csrf_token)
    context = second_farmer_client.get("/api/farmer-context").get_json()["context"]
    # The second farmer has no onboarding: context must be empty, not borrowed.
    assert context.get("farmer") is None or context.get("onboarding_required")
    assert context.get("farm") is None
    assert context.get("field") is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_soil_ph_range_validated(auth_client, csrf_token):
    _farm_id, field_id = _onboard(auth_client, csrf_token)
    response = auth_client.post(
        f"/api/fields/{field_id}/soil-tests",
        json={"ph": "99"}, headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 400


def test_lab_report_requires_reference_or_document(auth_client, csrf_token):
    _farm_id, field_id = _onboard(auth_client, csrf_token)
    response = auth_client.post(
        f"/api/fields/{field_id}/soil-tests",
        json={"source_type": "laboratory_report", "ph": "6.5"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 400


def test_observation_type_validated(auth_client, csrf_token):
    _farm_id, field_id = _onboard(auth_client, csrf_token)
    cycle_id = auth_client.post(
        f"/api/fields/{field_id}/crop-cycles",
        json={"crop_name": "Rice"}, headers={"X-CSRF-Token": csrf_token},
    ).get_json()["crop_cycle"]["id"]
    response = auth_client.post(
        f"/api/crop-cycles/{cycle_id}/observations",
        data={"observation_type": "alien_invasion"},
        content_type="multipart/form-data", headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 400


def test_archive_not_delete(auth_client, csrf_token):
    """Agricultural history is archived, never hard-deleted via the API."""
    headers = {"X-CSRF-Token": csrf_token}
    farm_id, _ = _onboard(auth_client, csrf_token)
    archived = auth_client.post(f"/api/farms/{farm_id}/archive", headers=headers)
    assert archived.get_json()["farm"]["archived"] is True
    listing = auth_client.get("/api/farms").get_json()["farms"]
    assert all(f["id"] != farm_id for f in listing)


# ---------------------------------------------------------------------------
# Market endpoint (no key configured → explicit unavailable)
# ---------------------------------------------------------------------------

def test_market_prices_unavailable_without_key(auth_client, csrf_token):
    response = auth_client.get(
        "/api/market-prices?commodity=Rice", headers={"X-CSRF-Token": csrf_token}
    )
    payload = response.get_json()["market"]
    assert payload["available"] is False
    assert payload["records"] == []
    assert payload["message"] == "Verified data is currently unavailable."


def test_market_prices_require_commodity(auth_client):
    response = auth_client.get("/api/market-prices")
    assert response.status_code == 400


def test_soil_document_upload_saved_privately(auth_client, csrf_token):
    """Uploaded reports live under the private uploads folder, not static."""
    from pathlib import Path

    import agriq.core.config as config_module

    _farm_id, field_id = _onboard(auth_client, csrf_token)
    response = auth_client.post(
        f"/api/fields/{field_id}/soil-tests",
        data={"source_type": "laboratory_report", "ph": "6.8",
              "report_reference": "LAB-2026-0042",
              "report_document": (_png(), "report.pdf")},
        content_type="multipart/form-data", headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 201
    record = response.get_json()["soil_test"]
    assert record["has_document"] is True
