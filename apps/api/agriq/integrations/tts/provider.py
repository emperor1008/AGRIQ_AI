"""Text-to-speech provider contract re-export.

The canonical ``SynthesisResult``/``TextToSpeechProvider`` definitions live
in ``agriq/integrations/speech/provider.py`` (shared by ASR, TTS and
translation). This module re-exports them for TTS-side imports.
"""
from ..speech.provider import SynthesisResult, TextToSpeechProvider  # noqa: F401

__all__ = ["SynthesisResult", "TextToSpeechProvider"]
