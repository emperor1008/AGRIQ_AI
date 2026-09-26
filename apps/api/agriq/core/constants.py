"""Application-wide constants."""
from __future__ import annotations

from typing import Mapping

# --- Session keys ---------------------------------------------------------
SESSION_USER_KEY = "user_contact"
SESSION_MODE_KEY = "user_mode"

# --- Modes ----------------------------------------------------------------
MODE_FARMER = "farmer"
MODE_STUDENT = "student"
DEFAULT_MODE = MODE_FARMER

# --- Input validation limits (Security and Access document) ---------------
MAX_INPUT_LENGTH = 200
MAX_QUESTION_LENGTH = 2000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
ALLOWED_UPLOAD_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_UPLOAD_MIMES = {"image/jpeg", "image/png", "image/webp"}

# --- Rate limits per IP (03_SECURITY_AND_ACCESS.md) -----------------------
RATE_LIMIT_LOGIN = "8 per minute"
RATE_LIMIT_ASSISTANT = "12 per minute"
RATE_LIMIT_ANALYSIS = "20 per minute"
RATE_LIMIT_WEATHER = "30 per minute"

# --- Provider endpoints ---------------------------------------------------
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
DATA_GOV_IN_MARKET_RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
DATA_GOV_IN_API_URL = "https://api.data.gov.in/resource/{resource_id}"

# --- External data provenance labels (DATA_PROVENANCE.md) -----------------
PROVIDER_OPEN_METEO = "Open-Meteo"
PROVIDER_AGMARKNET = "AGMARKNET via data.gov.in"
PROVIDER_OPENSTREETMAP = "OpenStreetMap"
PROVIDER_GEMINI = "Google Gemini"

#: Canonical unavailable-state message (never substitute generated values).
UNAVAILABLE_MESSAGE = "Verified data is currently unavailable."
#: Unanalysed districts on the map display this until a real analysis runs.
AWAITING_ANALYSIS_MESSAGE = "Awaiting verified analysis."
#: Shown wherever a price/quantity would need market data we do not have.
NO_VERIFIED_MARKET_MESSAGE = (
    "No verified market figures are available. Live mandi prices come only from "
    "the AGMARKNET provider; when it cannot be reached AGRIQ shows no number "
    "rather than an estimate."
)
#: Shown wherever a rupee figure would need yield/cost data we do not have.
NO_VERIFIED_IMPACT_MESSAGE = (
    "Not estimated. A rupee impact needs a verified yield, cost and price basis, "
    "none of which AGRIQ has for this crop yet."
)
# --- Canonical honest-state tokens (Phase 7 §3) ---------------------------
# ONE vocabulary for "we do not have real data / a validated model for this".
# Every module must emit these tokens instead of inventing its own wording, so
# a unified consumer can branch on a single set of states. A token is a claim
# about what AGRIQ does NOT know; it must never be replaced by a guess.
TOKEN_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
TOKEN_INSUFFICIENT_REAL_DATA = "INSUFFICIENT_REAL_DATA"
TOKEN_MODEL_NOT_VALIDATED = "MODEL_NOT_VALIDATED"
TOKEN_MODEL_NOT_REQUIRED = "MODEL_NOT_REQUIRED"
TOKEN_MODEL_TRAINING_BLOCKED = "MODEL_TRAINING_BLOCKED"
TOKEN_INSUFFICIENT_REAL_DATA_FOR_TRAINING = "INSUFFICIENT_REAL_DATA_FOR_TRAINING"
TOKEN_CONFIDENCE_NOT_CALIBRATED = "CONFIDENCE_NOT_CALIBRATED"
TOKEN_PROBABILITY_NOT_CALIBRATED = "PROBABILITY_NOT_CALIBRATED"
TOKEN_RECOMMENDATION_BLOCKED = "RECOMMENDATION_BLOCKED_INSUFFICIENT_DATA"
TOKEN_INSUFFICIENT_SAMPLE_SIZE = "INSUFFICIENT_SAMPLE_SIZE"
TOKEN_DATASET_NOT_APPROVED = "DATASET_NOT_APPROVED"
TOKEN_IMAGE_ANALYSIS_UNCERTAIN = "IMAGE_ANALYSIS_UNCERTAIN"
TOKEN_VOICE_TRANSCRIPTION_FAILED = "VOICE_TRANSCRIPTION_FAILED"
TOKEN_WEATHER_DATA_UNAVAILABLE = "WEATHER_DATA_UNAVAILABLE"
TOKEN_CROP_STAGE_UNKNOWN = "CROP_STAGE_UNKNOWN"
TOKEN_ROUTE_DATA_UNAVAILABLE = "ROUTE_DATA_UNAVAILABLE"
TOKEN_NET_VALUE_INCOMPLETE = "NET_VALUE_INCOMPLETE"
TOKEN_CACHED = "CACHED"
TOKEN_HEURISTIC_NOT_VALIDATED = "HEURISTIC_NOT_VALIDATED"
TOKEN_YIELD_IMPACT_NOT_MEASURED = "YIELD_IMPACT_NOT_MEASURED"

#: Human-readable basis strings for the rule-based (non-ML, non-calibrated)
#: parts of the Phase 3 dashboard intelligence. These exist so the UI can show
#: WHAT a number is, instead of presenting a heuristic as a measurement.
BASIS_RULE_HEURISTIC = (
    "Rule-based heuristic over farmer-entered crop, stage and field values plus "
    "verified weather. Not a validated model and not a field measurement."
)
BASIS_UNCALIBRATED_SCREENING = (
    "Rule-based screening band computed from the inputs above. Not a calibrated "
    "probability, so it must not be read as one."
)
BASIS_IMAGE_COLOUR_HEURISTIC = (
    "Colour-pattern screening over the uploaded image (green/yellow/brown/dark "
    "pixel proportions). Not a trained crop-disease model and not a diagnosis."
)

#: Upload size/type rules.
MAX_SOIL_REPORT_BYTES = 5 * 1024 * 1024  # 5 MiB
ALLOWED_SOIL_REPORT_MIMES = {"application/pdf", "image/jpeg", "image/png"}
ALLOWED_SOIL_REPORT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}

# --- Weather code text table (Open-Meteo WMO codes) -----------------------
WEATHER_CODE_TEXT: Mapping[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}

# --- Map marker palette (matches UI legend) -------------------------------
MARKER_COLORS: Mapping[str, str] = {
    "red": "#ef4444",
    "orange": "#f97316",
    "yellow": "#facc15",
    "green": "#22c55e",
}

DEFAULT_DISTRICT = "Cuttack"
DEFAULT_CROP = "Rice"
