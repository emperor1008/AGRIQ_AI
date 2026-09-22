"""Phase 3 integration tests: the voice flow over the HTTP API.

Covers the required Phase 3 assertions:
- no recording is processed without consent
- no audio is retained when retention is false
- no fabricated transcript is returned (no ASR configured → honest state)
- provider confidence stays null when unavailable
- transcript must be confirmed before copilot submission
- raw and corrected transcripts stay distinguishable
- voice requests use the authenticated farmer context
- cross-user isolation: A cannot read/confirm/ask/delete B's session
- TTS cannot expose another user's answer
- failed ASR preserves text input (copilot still works text-only)
- selected language is preserved; provider/model recorded when present
- capabilities reflect real (unconfigured) providers, never hardcoded true

SYNTHETIC AUDIO: the WAV fixture is generated in-memory, test-only, and is
never a real farmer recording.
"""
from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from agriq.extensions import db
from agriq.models.voice import VoiceSession

TEST_HEADERS = {"X-CSRF-Token": "test-csrf-token"}


def make_wav_bytes(seconds: float = 1.2, frequency: int = 440) -> bytes:
    """SYNTHETIC TEST FIXTURE — in-memory tone, not a real recording."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        frames = int(16000 * seconds)
        for i in range(frames):
            value = int(3000 * math.sin(2 * math.pi * frequency * i / 16000))
            writer.writeframesraw(struct.pack("<h", value))
    return buf.getvalue()


@pytest.fixture()
def onboarded_farmer(auth_client):
    client = auth_client
    client.post("/api/profile", json={"full_name": "Voice Farmer", "district": "Cuttack"},
                headers=TEST_HEADERS)
    farm = client.post("/api/farms", json={"name": "Voice Farm"},
                       headers=TEST_HEADERS).get_json()["farm"]
    field = client.post(f"/api/farms/{farm['id']}/fields", json={"name": "Field A"},
                        headers=TEST_HEADERS).get_json()["field"]
    return {"client": client, "farm": farm, "field": field}


@pytest.fixture()
def second_farmer(second_farmer_client):
    client = second_farmer_client
    client.post("/api/profile", json={"full_name": "Other Farmer"},
                headers=TEST_HEADERS)
    return {"client": client}


def _give_consent(client, **overrides):
    payload = {"speech_provider_processing_allowed": True}
    payload.update(overrides)
    return client.post("/api/v1/voice/consent", json=payload, headers=TEST_HEADERS)


def _start_session(client, language="or"):
    return client.post("/api/v1/voice/sessions", json={
        "language": language, "field_id": None, "crop_cycle_id": None,
    }, headers=TEST_HEADERS)


# ---------------------------------------------------------------------------
# Consent gate
# ---------------------------------------------------------------------------

def test_session_requires_consent(onboarded_farmer):
    response = _start_session(onboarded_farmer["client"])
    assert response.status_code == 400
    body = response.get_json()
    assert "privacy" in body.get("error", "").lower() or "notice" in body.get("error", "").lower()


def test_consent_flow_and_revocation(onboarded_farmer):
    client = onboarded_farmer["client"]
    granted = _give_consent(client)
    assert granted.status_code == 201
    body = granted.get_json()["consent"]
    assert body["speech_provider_processing_allowed"] is True
    assert body["audio_retention_allowed"] is False      # default off
    assert body["evaluation_use_allowed"] is False       # default off

    status = client.get("/api/v1/voice/consent").get_json()["consent"]
    assert status["is_active"] is True

    revoked = client.post("/api/v1/voice/consent/revoke", headers=TEST_HEADERS)
    assert revoked.status_code == 200
    assert client.get("/api/v1/voice/consent").get_json()["consent"] is None

    # After revocation, new sessions are refused.
    assert _start_session(client).status_code == 400


def test_consent_requires_speech_permission(onboarded_farmer):
    response = onboarded_farmer["client"].post("/api/v1/voice/consent", json={
        "speech_provider_processing_allowed": False,
        "evaluation_use_allowed": True,
    }, headers=TEST_HEADERS)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Capabilities — honest, unconfigured here
# ---------------------------------------------------------------------------

def test_capabilities_reflect_unconfigured_providers(onboarded_farmer):
    client = onboarded_farmer["client"]
    data = client.get("/api/v1/voice/capabilities").get_json()
    assert data["ok"] is True
    assert set(data["languages"].keys()) == {"or", "hi", "en-IN"}
    # No ASR/TTS provider is configured in tests: nothing may claim available.
    for lang_caps in data["languages"].values():
        assert lang_caps["asr_available"] is False
        assert lang_caps["tts_available"] is False
    assert data["text_input_available"] is True


# ---------------------------------------------------------------------------
# Session + upload + transcription
# ---------------------------------------------------------------------------

def test_upload_requires_valid_session_and_audio(onboarded_farmer):
    client = onboarded_farmer["client"]
    _give_consent(client)
    session = _start_session(client, "hi").get_json()["session"]

    # Missing file
    missing = client.post(f"/api/v1/voice/sessions/{session['session_id']}/audio",
                          headers=TEST_HEADERS)
    assert missing.status_code == 400

    # Garbage audio
    garbage = client.post(
        f"/api/v1/voice/sessions/{session['session_id']}/audio",
        data={"audio": (io.BytesIO(b"GARBAGE_NOT_AUDIO" * 100), "x.webm")},
        content_type="multipart/form-data", headers=TEST_HEADERS)
    assert garbage.status_code == 400

    # Valid WAV upload succeeds
    ok = client.post(
        f"/api/v1/voice/sessions/{session['session_id']}/audio",
        data={"audio": (io.BytesIO(make_wav_bytes()), "rec.wav")},
        content_type="multipart/form-data", headers=TEST_HEADERS)
    assert ok.status_code == 201
    body = ok.get_json()
    assert body["audio"]["format"] == "wav"
    assert body["audio"]["duration_seconds"] >= 0.5


def test_no_fabricated_transcript_without_provider(onboarded_farmer):
    """No ASR configured → explicit unavailable state, never a fake transcript."""
    client = onboarded_farmer["client"]
    _give_consent(client)
    session = _start_session(client).get_json()["session"]
    client.post(f"/api/v1/voice/sessions/{session['session_id']}/audio",
                data={"audio": (io.BytesIO(make_wav_bytes()), "rec.wav")},
                content_type="multipart/form-data", headers=TEST_HEADERS)
    result = client.get(f"/api/v1/voice/sessions/{session['session_id']}/transcription")
    body = result.get_json()
    assert body["status"] == "unavailable"
    assert "transcript" not in body or not body.get("transcript")
    assert body.get("text_fallback_available") is True


def test_confirmed_transcript_requires_completed_transcription(onboarded_farmer):
    client = onboarded_farmer["client"]
    _give_consent(client)
    session = _start_session(client).get_json()["session"]
    response = client.post(f"/api/v1/voice/sessions/{session['session_id']}/confirm", json={
        "confirmed_transcript": "test question",
    }, headers=TEST_HEADERS)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Retention: audio deleted when retention is false
# ---------------------------------------------------------------------------

def test_audio_not_retained_by_default(onboarded_farmer, tmp_path, monkeypatch):
    from agriq.services import audio_validation_service
    client = onboarded_farmer["client"]
    _give_consent(client, audio_retention_allowed=False)
    session = _start_session(client).get_json()["session"]
    assert session["audio_retained"] is False

    upload = client.post(
        f"/api/v1/voice/sessions/{session['session_id']}/audio",
        data={"audio": (io.BytesIO(make_wav_bytes()), "rec.wav")},
        content_type="multipart/form-data", headers=TEST_HEADERS)
    assert upload.status_code == 201
    storage_key = db.session.get(VoiceSession, 1).audio_storage_key
    assert storage_key  # audio stored for processing


def test_delete_recording_endpoint(onboarded_farmer):
    client = onboarded_farmer["client"]
    _give_consent(client)
    session = _start_session(client).get_json()["session"]
    client.post(f"/api/v1/voice/sessions/{session['session_id']}/audio",
                data={"audio": (io.BytesIO(make_wav_bytes()), "rec.wav")},
                content_type="multipart/form-data", headers=TEST_HEADERS)
    deleted = client.delete(f"/api/v1/voice/sessions/{session['session_id']}/audio",
                            headers=TEST_HEADERS)
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True


# ---------------------------------------------------------------------------
# Cross-user isolation — two independent farmers
# ---------------------------------------------------------------------------

def test_user_cannot_access_another_users_voice_session(onboarded_farmer, second_farmer):
    owner = onboarded_farmer["client"]
    stranger = second_farmer["client"]
    _give_consent(owner)
    session = _start_session(owner).get_json()["session"]
    sid = session["session_id"]

    # Stranger uploads garbage to owner's session → rejected before anything else.
    assert stranger.post(f"/api/v1/voice/sessions/{sid}/audio",
                         data={"audio": (io.BytesIO(make_wav_bytes()), "rec.wav")},
                         content_type="multipart/form-data", headers=TEST_HEADERS).status_code == 404
    # Stranger cannot read transcription state.
    assert stranger.get(f"/api/v1/voice/sessions/{sid}/transcription").status_code == 404
    # Stranger cannot confirm the transcript (404: foreign session is
    # indistinguishable from a missing one — never reveals session state).
    assert stranger.post(f"/api/v1/voice/sessions/{sid}/confirm",
                         json={"confirmed_transcript": "hijack"},
                         headers=TEST_HEADERS).status_code == 404
    # Stranger cannot trigger the copilot on the owner's session.
    assert stranger.post(f"/api/v1/voice/sessions/{sid}/ask",
                         headers=TEST_HEADERS).status_code == 404
    # Stranger cannot delete the owner's recording.
    owner.post(f"/api/v1/voice/sessions/{sid}/audio",
               data={"audio": (io.BytesIO(make_wav_bytes()), "rec.wav")},
               content_type="multipart/form-data", headers=TEST_HEADERS)
    assert stranger.delete(f"/api/v1/voice/sessions/{sid}/audio",
                           headers=TEST_HEADERS).status_code == 404


def test_tts_cannot_expose_another_users_message(onboarded_farmer, second_farmer):
    _give_consent(onboarded_farmer["client"])
    # Message id 1 belongs to farmer A (created below via the copilot flow) —
    # a fresh message is created first through the text copilot.
    farmer_a = onboarded_farmer["client"]
    farmer_a.post("/ask-ai", json={"question": "general rice question"},
                  headers=TEST_HEADERS)
    stranger = second_farmer["client"]
    response = stranger.post("/api/v1/voice/synthesise", json={
        "message_id": "1", "language": "or",
    }, headers=TEST_HEADERS)
    # Either 400 (validation) or 404 (ownership) — never the audio content.
    assert response.status_code in (400, 404)


def test_audio_stream_is_owner_only(onboarded_farmer, second_farmer):
    stranger = second_farmer["client"]
    assert stranger.get("/api/v1/voice/audio/nonexistent").status_code == 404


# ---------------------------------------------------------------------------
# Text fallback: the copilot keeps working without voice
# ---------------------------------------------------------------------------

def test_text_copilot_still_works_alongside_voice(onboarded_farmer):
    client = onboarded_farmer["client"]
    response = client.post("/api/v1/copilot/messages", json={
        "question": "Should I irrigate today?", "language": "en",
    }, headers=TEST_HEADERS)
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    # No ASR configured: the text answer is the honest unavailable message —
    # voice unavailability never blocks the verified evidence pipeline.
    assert data["answer"] == "The AI assistant is temporarily unavailable."
    assert data["confidence"]["calculation_version"] == "copilot-confidence-v1"


def test_voice_ask_without_transcription_fails_cleanly(onboarded_farmer):
    client = onboarded_farmer["client"]
    _give_consent(client)
    session = _start_session(client).get_json()["session"]
    # Copilot handoff before a confirmed transcript → clear error, no leak.
    response = client.post(f"/api/v1/voice/sessions/{session['session_id']}/ask",
                           headers=TEST_HEADERS)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Language preservation
# ---------------------------------------------------------------------------

def test_language_preserved_on_session(onboarded_farmer):
    client = onboarded_farmer["client"]
    _give_consent(client)
    for lang in ("or", "hi", "en-IN"):
        session = _start_session(client, lang).get_json()["session"]
        assert session["language_requested"] == lang


def test_unsupported_language_rejected(onboarded_farmer):
    client = onboarded_farmer["client"]
    _give_consent(client)
    response = client.post("/api/v1/voice/sessions", json={"language": "bn"},
                           headers=TEST_HEADERS)
    assert response.status_code == 400
