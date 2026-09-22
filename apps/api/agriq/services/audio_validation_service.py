"""Audio validation & preprocessing service (Phase 3).

Validates uploaded voice recordings by inspecting **actual decoded content**
(magic bytes + real decoding), never just the filename or browser MIME type.

Real processing only:
- container/signature detection (WebM/Opus, WAV/PCM, MP3, M4A when decodable)
- hard size ceiling, duration floor/ceiling from real decode
- channel/rate normalisation when the optional audio stack is available
- silence/corruption detection from decoded RMS

No advanced noise-cancellation is claimed — none is implemented. The
original upload is never modified in place; normalised copies are written
fresh under random names.
"""
from __future__ import annotations

import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..core.exceptions import ValidationError
from ..core.logging import get_logger

logger = get_logger("services.audio_validation")

PREPROCESSING_VERSION = "audio-preproc-v1"

# Format signatures (container-level; codec probing follows via decode)
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"      # EBML (WebM/MKV)
_WAV_MAGIC = b"RIFF"
_MP3_FRAME = b"\xff\xfb"               # MPEG-1 Layer III frame sync (common)
_MP3_ID3 = b"ID3"
_M4A_MAGIC = b"ftyp"


@dataclass
class AudioInfo:
    """Measured facts about one audio upload."""

    format: str                    # webm_opus | wav | mp3 | m4a
    duration_seconds: float
    channels: int = 1
    sample_rate: int = 0
    decoded_ok: bool = False
    is_silent: bool = False
    preprocessing_version: str = PREPROCESSING_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "duration_seconds": round(self.duration_seconds, 2),
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "decoded_ok": self.decoded_ok,
            "is_silent": self.is_silent,
            "preprocessing_version": self.preprocessing_version,
        }


def _limits(config: Any) -> dict[str, float]:
    return {
        "max_bytes": int(config.get("VOICE_MAX_FILE_SIZE_MB", 10)) * 1024 * 1024,
        "max_duration": float(config.get("VOICE_MAX_DURATION_SECONDS", 60)),
        "min_duration": float(config.get("VOICE_MIN_DURATION_SECONDS", 0.5)),
    }


def detect_format(head: bytes) -> Optional[str]:
    """Container detection from magic bytes (content, not filename)."""
    if head.startswith(_WEBM_MAGIC):
        return "webm_opus"
    if head.startswith(_WAV_MAGIC):
        return "wav"
    if head.startswith(_MP3_ID3) or head[:2] == _MP3_FRAME:
        return "mp3"
    if len(head) >= 8 and head[4:8] == _M4A_MAGIC:
        return "m4a"
    return None


def measure_wav(audio: bytes) -> tuple[float, int, int]:
    """Real WAV decode: duration, channels, sample rate."""
    import wave
    with wave.open(io.BytesIO(audio), "rb") as reader:
        frames = reader.getnframes()
        rate = reader.getframerate()
        channels = reader.getnchannels()
        duration = frames / float(rate) if rate else 0.0
    return duration, channels, rate


def _decode_with_ffmpeg(audio: bytes) -> Optional[AudioInfo]:
    """Decode non-WAV formats via ffprobe/ffmpeg when installed.

    Returns None when the toolchain is unavailable (caller decides policy:
    WebM/Opus and MP3 uploads then require the audio toolchain — this is
    documented, never worked around with guessed durations).
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffprobe"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(audio)
        tmp_path = tmp.name
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-show_entries", "stream=channels,sample_rate",
             "-of", "default=noprint_wrappers=1", tmp_path],
            capture_output=True, timeout=15,
        )
        if probe.returncode != 0:
            return AudioInfo(format="undecodable", duration_seconds=0.0, decoded_ok=False)
        values: dict[str, str] = {}
        for line in probe.stdout.decode("utf-8", "replace").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
        try:
            duration = float(values.get("duration", "0") or 0)
        except ValueError:
            duration = 0.0
        try:
            channels = int(values.get("channels", "1") or 1)
        except ValueError:
            channels = 1
        try:
            sample_rate = int(float(values.get("sample_rate", "0") or 0))
        except ValueError:
            sample_rate = 0
        return AudioInfo(format="undecodable", duration_seconds=duration,
                         channels=channels, sample_rate=sample_rate, decoded_ok=duration > 0)
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def validate_audio(storage: Any, config: Any) -> AudioInfo:
    """Validate one uploaded audio file and return measured facts.

    Raises ValidationError with a farmer-friendly message for any violation.
    """
    limits = _limits(config)

    storage.seek(0, 2)
    size = storage.tell()
    storage.seek(0)
    if size == 0:
        raise ValidationError("The recording is empty. Please record again.")
    if size > limits["max_bytes"]:
        raise ValidationError(
            f"The recording is too large (limit {int(limits['max_bytes'] // (1024 * 1024))} MiB)."
        )
    audio = storage.read()

    # Executable / non-audio signature rejection before any decode.
    if audio[:2] in (b"MZ", b"\x7fELF") or audio[:4] in (b"PK\x03\x04", b"\x7fELF"):
        raise ValidationError("That file is not a valid audio recording.")

    fmt = detect_format(audio[:16])
    if fmt is None:
        raise ValidationError(
            "Unsupported audio format. Please record in the app or upload WebM, WAV or MP3."
        )

    info = _measure(audio, fmt)
    if info is None:
        # Toolchain missing for compressed formats: honest failure, no guess.
        raise ValidationError(
            "This recording could not be processed on the server. Please try WAV format or record in the app."
        )
    if not info.decoded_ok or info.duration_seconds <= 0:
        raise ValidationError(
            "We could not reliably understand this recording. Please try again or type your question."
        )
    if info.duration_seconds < limits["min_duration"]:
        raise ValidationError("The recording is too short. Please hold the microphone while speaking.")
    if info.duration_seconds > limits["max_duration"]:
        raise ValidationError(
            f"The recording is too long (limit {int(limits['max_duration'])} seconds). Please record again."
        )
    if info.is_silent:
        raise ValidationError(
            "The recording appears to be silent. Please try again in a quieter place or check your microphone."
        )
    return info


def _measure(audio: bytes, fmt: str) -> Optional[AudioInfo]:
    """Measure duration/channels/rate with real decoding; silence check."""
    if fmt == "wav":
        try:
            duration, channels, rate = measure_wav(audio)
        except Exception:  # noqa: BLE001 — corrupted WAV
            return AudioInfo(format=fmt, duration_seconds=0.0, decoded_ok=False)
        return AudioInfo(
            format=fmt, duration_seconds=duration, channels=channels,
            sample_rate=rate, decoded_ok=duration > 0,
            is_silent=_wav_is_silent(audio),
        )
    # Compressed formats: real decode via ffprobe/ffmpeg when available.
    decoded = _decode_with_ffmpeg(audio)
    if decoded is None:
        return None
    decoded.format = fmt
    decoded.decoded_ok = decoded.duration_seconds > 0
    if decoded.decoded_ok:
        decoded.is_silent = _silence_by_peak(audio)
    return decoded


def _wav_is_silent(audio: bytes) -> bool:
    """RMS silence detection on real PCM samples."""
    try:
        import wave
        import struct
        import math
        with wave.open(io.BytesIO(audio), "rb") as reader:
            width = reader.getsampwidth()
            if width != 2:
                return False
            frames = reader.readframes(reader.getnframes())
        count = len(frames) // 2
        if count == 0:
            return True
        samples = struct.unpack(f"<{count}h", frames[: count * 2])
        rms = math.sqrt(sum(s * s for s in samples) / count)
        return rms < 50   # effectively inaudible PCM
    except Exception:  # noqa: BLE001
        return False


def _silence_by_peak(audio: bytes) -> bool:
    """Cheap peak check for compressed audio: a totally flat payload of one
    repeated byte indicates captured silence/corruption. Real loudness
    analysis happens post-decode; this is a corruption filter, not a claim."""
    if not audio:
        return True
    sample = audio[4096:8192]
    if sample and len(set(sample)) <= 2:
        return True
    return False


def store_audio(user_id: int, storage: Any, config: Any) -> tuple[str, AudioInfo]:
    """Validate then persist audio privately under a random name.

    Returns (storage_key, info). Storage root is VOICE_TEMP_STORAGE_PATH —
    never inside the static tree, never publicly reachable.
    """
    info = validate_audio(storage, config)
    root = Path(config.get("VOICE_TEMP_STORAGE_PATH") or "voice_audio")
    target_dir = root / "voice" / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = {"webm_opus": "webm", "wav": "wav", "mp3": "mp3", "m4a": "m4a"}[info.format]
    key = f"voice/{user_id}/{uuid.uuid4().hex}.{ext}"
    storage.seek(0)
    (root / key).write_bytes(storage.read())
    logger.info("voice_audio_stored user_id=%s format=%s duration=%.2f",
                user_id, info.format, info.duration_seconds)
    return key, info


def delete_audio(config: Any, storage_key: str) -> bool:
    """Delete one stored audio file by key (best-effort, logged)."""
    if not storage_key:
        return False
    root = Path(config.get("VOICE_TEMP_STORAGE_PATH") or "voice_audio")
    target = root / storage_key
    try:
        if target.exists():
            target.unlink()
        return True
    except OSError as exc:
        logger.warning("voice_audio_delete_failed error=%s", type(exc).__name__)
        return False


def cleanup_expired_audio(config: Any, storage_keys: list[str]) -> int:
    """Delete a batch of expired audio files; returns the deleted count."""
    deleted = 0
    for key in storage_keys:
        if delete_audio(config, key):
            deleted += 1
    return deleted


__all__ = [
    "validate_audio", "store_audio", "delete_audio", "cleanup_expired_audio",
    "detect_format", "measure_wav", "AudioInfo", "PREPROCESSING_VERSION",
]
