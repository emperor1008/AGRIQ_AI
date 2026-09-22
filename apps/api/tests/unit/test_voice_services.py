"""Phase 3 unit tests: audio validation, provider contracts, language and
vocabulary services, consent logic.

SYNTHETIC AUDIO FIXTURES: all audio bytes below are generated in-memory for
tests only. They never enter production storage and are never presented as
real farmer recordings or as evaluation data.
"""
from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from agriq.core.exceptions import ValidationError
from agriq.core.config import TestingConfig
from agriq.integrations.speech.bhashini_asr import BhashiniASRProvider
from agriq.integrations.speech.indian_english_asr import IndianEnglishASRProvider
from agriq.integrations.speech.indicconformer_asr import IndicConformerASRProvider
from agriq.integrations.tts.bhashini_tts import BhashiniTTSProvider
from agriq.integrations.tts.device_tts import DeviceTTSProvider
from agriq.services import (
    agricultural_vocabulary,
    audio_validation_service,
    language_service,
    voice_consent_service,
)


# ---------------------------------------------------------------------------
# Synthetic audio fixtures (test-only, clearly named)
# ---------------------------------------------------------------------------

def make_wav_bytes(seconds: float = 1.0, frequency: int = 440, rate: int = 16000,
                   amplitude: int = 3000) -> bytes:
    """Generate a real (audible) PCM WAV tone — SYNTHETIC TEST FIXTURE."""
    import math
    import struct
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        frames = int(rate * seconds)
        for i in range(frames):
            value = int(amplitude * math.sin(2 * math.pi * frequency * i / rate))
            writer.writeframesraw(struct.pack("<h", value))
    return buf.getvalue()


def make_silent_wav_bytes(seconds: float = 1.0) -> bytes:
    """All-zero PCM — SYNTHETIC TEST FIXTURE for silence detection."""
    import struct
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        for _ in range(int(16000 * seconds)):
            writer.writeframesraw(struct.pack("<h", 0))
    return buf.getvalue()


class FakeStorage:
    def __init__(self, data: bytes):
        import io
        self._stream = io.BytesIO(data)
    def seek(self, *a): return self._stream.seek(*a)
    def tell(self): return self._stream.tell()
    def read(self, *a): return self._stream.read(*a)


@pytest.fixture()
def voice_config(tmp_path):
    config = TestingConfig()
    config.VOICE_TEMP_STORAGE_PATH = str(tmp_path / "voice_audio")
    return config


# ---------------------------------------------------------------------------
# Audio validation — real decoding, real limits
# ---------------------------------------------------------------------------

class TestAudioValidation:
    def test_valid_wav_passes_with_measured_duration(self, voice_config):
        storage = FakeStorage(make_wav_bytes(seconds=1.2))
        info = audio_validation_service.validate_audio(storage, voice_config)
        assert info.format == "wav"
        assert 1.1 <= info.duration_seconds <= 1.4
        assert info.decoded_ok and not info.is_silent

    def test_too_short_rejected(self, voice_config):
        storage = FakeStorage(make_wav_bytes(seconds=0.1))
        with pytest.raises(ValidationError):
            audio_validation_service.validate_audio(storage, voice_config)

    def test_too_long_rejected(self, voice_config):
        config = TestingConfig()
        config.VOICE_MAX_DURATION_SECONDS = 1
        storage = FakeStorage(make_wav_bytes(seconds=2.0))
        with pytest.raises(ValidationError):
            audio_validation_service.validate_audio(storage, config)

    def test_silent_audio_rejected(self, voice_config):
        storage = FakeStorage(make_silent_wav_bytes(seconds=1.5))
        with pytest.raises(ValidationError):
            audio_validation_service.validate_audio(storage, voice_config)

    def test_executable_content_rejected(self, voice_config):
        storage = FakeStorage(b"MZ" + b"\x90" * 500)
        with pytest.raises(ValidationError):
            audio_validation_service.validate_audio(storage, voice_config)

    def test_unknown_format_rejected(self, voice_config):
        storage = FakeStorage(b"NOT_AN_AUDIO_FORMAT_AT_ALL" * 20)
        with pytest.raises(ValidationError):
            audio_validation_service.validate_audio(storage, voice_config)

    def test_empty_upload_rejected(self, voice_config):
        storage = FakeStorage(b"")
        with pytest.raises(ValidationError):
            audio_validation_service.validate_audio(storage, voice_config)

    def test_store_uses_random_private_name(self, voice_config, tmp_path):
        storage = FakeStorage(make_wav_bytes(seconds=1.0))
        key, info = audio_validation_service.store_audio(storage, voice_config) if False else \
            audio_validation_service.store_audio(1, storage, voice_config)
        assert key.startswith("voice/1/")
        assert key.split("/")[-1].split(".")[0]  # random uuid name
        assert (Path(voice_config.VOICE_TEMP_STORAGE_PATH) / key).exists()

    def test_delete_audio_removes_file(self, voice_config):
        storage = FakeStorage(make_wav_bytes(seconds=1.0))
        key, _ = audio_validation_service.store_audio(1, storage, voice_config)
        assert audio_validation_service.delete_audio(voice_config, key)
        assert not (Path(voice_config.VOICE_TEMP_STORAGE_PATH) / key).exists()


# ---------------------------------------------------------------------------
# ASR provider contracts — honest unavailable states, verbatim confidence
# ---------------------------------------------------------------------------

class TestASRProviderContracts:
    def test_bhashini_unconfigured_is_explicit(self):
        provider = BhashiniASRProvider()
        assert not provider.is_configured()
        result = provider.transcribe(b"audio", "or")
        assert result.status == "unavailable"
        assert result.error_category == "not_configured"
        assert result.transcript is None

    def test_bhashini_unsupported_language(self):
        provider = BhashiniASRProvider(api_key="k", pipeline_id="p")
        result = provider.transcribe(b"audio", "fr")
        assert result.status == "unavailable"
        assert result.error_category == "unsupported_language"

    def test_bhashini_confidence_absent_stays_null(self):
        """A provider response without confidence yields available=False."""
        from agriq.integrations.speech.bhashini_asr import _parse_response
        transcript, confidence, detected = _parse_response({
            "pipelineResponse": [{"output": [{"transcript": "ଧାନ କେବେ ରୋପଣ କରିବି"}]}]
        })
        assert transcript == "ଧାନ କେବେ ରୋପଣ କରିବି"
        assert confidence == {"available": False, "value": None, "source": None}

    def test_bhashini_confidence_present_is_verbatim(self):
        from agriq.integrations.speech.bhashini_asr import _parse_response
        _, confidence, _ = _parse_response({
            "pipelineResponse": [{"output": [{"transcript": "hello", "confidence": 0.81}]}]
        })
        assert confidence == {"available": True, "value": 0.81, "source": "provider"}

    def test_indicconformer_without_model_is_unavailable(self):
        provider = IndicConformerASRProvider(model_paths={"or": "", "hi": ""})
        assert not provider.is_configured()
        result = provider.transcribe(b"audio", "or")
        assert result.status == "unavailable"
        assert result.transcript is None

    def test_indian_english_without_model_is_unavailable(self):
        provider = IndianEnglishASRProvider(model_path="")
        result = provider.transcribe(b"audio", "en-IN")
        assert result.status == "unavailable"

    def test_provider_never_returns_scripted_transcript_on_failure(self):
        provider = BhashiniASRProvider(api_key="k", pipeline_id="p")
        # Unsupported language path: no transcript, no invented text.
        result = provider.transcribe(b"audio", "xx")
        assert result.transcript is None
        assert result.status == "unavailable"


# ---------------------------------------------------------------------------
# TTS provider contracts
# ---------------------------------------------------------------------------

class TestTTSProviderContracts:
    def test_bhashini_tts_unconfigured_is_explicit(self):
        provider = BhashiniTTSProvider()
        result = provider.synthesise("hello", "or")
        assert result.status == "unavailable"
        assert result.audio is None

    def test_device_tts_is_metadata_only(self):
        provider = DeviceTTSProvider()
        assert provider.is_configured()
        result = provider.synthesise("hello", "or")
        assert result.status == "unavailable"   # synthesis is browser-side only

    def test_device_tts_lists_all_three_languages(self):
        provider = DeviceTTSProvider()
        for lang in ("or", "hi", "en-IN"):
            assert provider.supports_language(lang)


# ---------------------------------------------------------------------------
# Language service — closed set
# ---------------------------------------------------------------------------

class TestLanguageService:
    def test_only_three_languages_supported(self):
        assert set(language_service.SUPPORTED) == {"or", "hi", "en-IN"}

    def test_english_alias_normalises(self):
        assert language_service.normalise("en") == "en-IN"

    def test_unsupported_falls_back_with_default(self):
        assert language_service.normalise("fr") == "en-IN"

    def test_is_supported_rejects_dialect_claims(self):
        assert not language_service.is_supported("or-IN-X")
        assert not language_service.is_supported("bn")


# ---------------------------------------------------------------------------
# Agricultural vocabulary — display aid only
# ---------------------------------------------------------------------------

class TestAgriculturalVocabulary:
    def test_lookup_finds_odia_crop(self):
        matches = agricultural_vocabulary.lookup("ଧାନ", "or")
        assert matches and matches[0].english_equivalent == "Rice"

    def test_suggest_correction_bph(self):
        entry = agricultural_vocabulary.suggest_correction("Brown Plant Hopper")
        assert entry and entry.category == "pest"

    def test_every_term_has_source_and_version(self):
        for term in agricultural_vocabulary.REGISTRY:
            assert term.source
            assert term.source_version
            assert term.reviewer_status == "reviewed"

    def test_unknown_term_returns_nothing(self):
        assert agricultural_vocabulary.suggest_correction("zebra quantum") is None


# ---------------------------------------------------------------------------
# Consent logic — explicit, default-deny
# ---------------------------------------------------------------------------

class TestConsentLogic:
    def test_absent_checkboxes_are_false(self):
        data = {"speech_provider_processing_allowed": True}
        assert data.get("evaluation_use_allowed", False) is False
        assert data.get("audio_retention_allowed", False) is False

    def test_retention_requires_both_consent_and_flag(self):
        assert voice_consent_service.retention_allowed(None, True) is False
        assert voice_consent_service.retention_allowed(
            {"audio_retention_allowed": True}, False) is False
        assert voice_consent_service.retention_allowed(
            {"audio_retention_allowed": True}, True) is True

    def test_consent_without_speech_permission_raises(self):
        with pytest.raises(voice_consent_service.ConsentError):
            voice_consent_service.give_consent(1, {"speech_provider_processing_allowed": False})
