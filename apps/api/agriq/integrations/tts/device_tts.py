"""Device-native TTS metadata provider (Phase 3).

The browser's speechSynthesis API is the *device* voice. It never runs
server-side; this module only exposes its capability metadata so the
capabilities endpoint can list it honestly as a **device fallback** —
explicitly labelled in the UI as the device's own voice, not AGRIQ's
validated TTS. It cannot be recorded, stored or measured, and it is never
automatically selected over a configured real provider.
"""
from __future__ import annotations

from typing import Any

from .provider import SynthesisResult

SUPPORTED_LANGUAGES = {"or", "hi", "en-IN"}


class DeviceTTSProvider:
    """Metadata-only provider representing the browser/device voice."""

    def is_configured(self) -> bool:
        # Always "configured": the device voice is a browser capability,
        # detected client-side at runtime.
        return True

    def supports_language(self, language_code: str) -> bool:
        return language_code in SUPPORTED_LANGUAGES

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "provider": "device-tts",
            "configured": True,
            "languages": sorted(SUPPORTED_LANGUAGES),
            "licence": "Device/browser capability (no AGRIQ model)",
            "processing_location": "farmer's device",
            "note": "Explicitly labelled fallback; quality depends on the device.",
        }

    def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "reason": None}

    def synthesise(self, text: str, language_code: str) -> SynthesisResult:
        # Server-side synthesis is not possible for the device voice.
        return SynthesisResult(
            status="unavailable", provider="device-tts", language=language_code,
            error_category="not_configured",
            reason="Device voice synthesis happens in the browser, not the server.",
        )


__all__ = ["DeviceTTSProvider", "SUPPORTED_LANGUAGES"]
