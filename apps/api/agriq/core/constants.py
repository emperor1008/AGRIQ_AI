"""Application-wide constants."""
from __future__ import annotations

from typing import Mapping

# --- Session keys ---------------------------------------------------------
SESSION_USER_KEY = "user_contact"
SESSION_MODE_KEY = "user_mode"
#: Phase 7.1: opaque session token (raw value) + row id for server-side sessions.
SESSION_TOKEN_KEY = "session_token"
SESSION_ID_KEY = "session_id"

# --- Authentication states (§22 structured error codes) -------------------
AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
AUTH_ACCOUNT_DISABLED = "AUTH_ACCOUNT_DISABLED"
AUTH_EMAIL_NOT_VERIFIED = "AUTH_EMAIL_NOT_VERIFIED"
AUTH_RATE_LIMITED = "AUTH_RATE_LIMITED"
AUTH_PASSWORD_RESET_UNAVAILABLE = "AUTH_PASSWORD_RESET_UNAVAILABLE"
AUTH_EMAIL_VERIFICATION_UNAVAILABLE = "AUTH_EMAIL_VERIFICATION_UNAVAILABLE"
AUTH_CONFIGURATION_ERROR = "AUTH_CONFIGURATION_ERROR"
AUTH_INVALID_RESET_TOKEN = "AUTH_INVALID_RESET_TOKEN"
AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
AUTH_DUPLICATE_ACCOUNT = "AUTH_DUPLICATE_ACCOUNT"
AUTH_WEAK_PASSWORD = "AUTH_WEAK_PASSWORD"
AUTH_PASSWORD_MISMATCH = "AUTH_PASSWORD_MISMATCH"
AUTH_VALIDATION = "AUTH_VALIDATION"
AUTH_OK = "AUTH_OK"
#: Honest states for infrastructure that is genuinely absent (§13/§14/§30).
PASSWORD_RESET_EMAIL_UNAVAILABLE = "PASSWORD_RESET_EMAIL_UNAVAILABLE"
EMAIL_VERIFICATION_UNAVAILABLE = "EMAIL_VERIFICATION_UNAVAILABLE"
EMAIL_VERIFICATION_NOT_REQUIRED = "EMAIL_VERIFICATION_NOT_REQUIRED"
OTP_PROVIDER_UNAVAILABLE = "OTP_PROVIDER_UNAVAILABLE"

# --- Password policy (03_SECURITY_AND_ACCESS.md) --------------------------
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
#: Contact ownership is not claimed until a real email/OTP provider exists.
EMAIL_VERIFICATION_REQUIRED = False

# --- Session lifetimes ----------------------------------------------------
#: Sliding window: refreshed while the user keeps making requests.
SESSION_IDLE_TIMEOUT_HOURS = 8
#: Absolute cap: a session can never be extended past this.
SESSION_ABSOLUTE_TIMEOUT_HOURS = 24 * 30
#: Password-reset tokens are short-lived and single-use.
PASSWORD_RESET_TTL_MINUTES = 30

#: Generic credential failure text (never reveals which factor failed).
AUTH_GENERIC_FAILURE_MESSAGE = "Invalid contact or password."

#: Recovery endpoint states — no email is ever claimed as sent without a provider.
PASSWORD_RESET_UNAVAILABLE_MESSAGE = (
    "Password recovery is not available on this deployment: no email provider is "
    "configured. Ask the AGRIQ administrator to configure email delivery, then try "
    "again. Your password has not been changed."
)
PASSWORD_RESET_REQUEST_ACK_MESSAGE = (
    "If that contact has an AGRIQ AI account, a password-reset link valid for a "
    "short time has been sent to it. Check the registered inbox or phone."
)

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

# --- External provider states (Phase 7.3 real-data reliability) -------------
# ONE machine-readable vocabulary for the state of every fetched external
# value (weather, mandi prices). The UI branches on ``state`` instead of
# guessing from a generic message, and a failure reason can never be rendered
# as if it were data. Each state also carries a human message that names the
# actual cause and never contains a credential.
STATE_OK = "OK"
STATE_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
STATE_DATA_SOURCE_ERROR = "DATA_SOURCE_ERROR"
STATE_INVALID_LOCATION = "INVALID_LOCATION"
STATE_DATA_STALE = "DATA_STALE"
STATE_CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
STATE_NO_OFFICIAL_RECORD = "NO_OFFICIAL_RECORD"
#: The provider deliberately gates this endpoint (captcha/authorisation).
#: AGRIQ does not attempt to defeat provider bot protection.
STATE_PROVIDER_ACCESS_GATED = "PROVIDER_ACCESS_GATED"

#: Provider failure reason codes (stable, used in JSON and log lines).
REASON_PROVIDER_REQUEST_FAILED = "provider_request_failed"
REASON_PROVIDER_TIMEOUT = "provider_timeout"
REASON_PROVIDER_HTTP_ERROR = "provider_http_error"
REASON_PROVIDER_MALFORMED_RESPONSE = "provider_malformed_response"
REASON_API_KEY_NOT_CONFIGURED = "api_key_not_configured"
REASON_NO_LOCATION = "no_location"
REASON_INVALID_COORDINATES = "invalid_coordinates"
REASON_NO_OFFICIAL_RECORD = "no_official_record"
REASON_NO_FIELD_COORDINATES = "no_field_coordinates"

STATE_MESSAGES: Mapping[str, str] = {
    STATE_DATA_UNAVAILABLE: UNAVAILABLE_MESSAGE,
    STATE_DATA_SOURCE_ERROR: (
        "Weather data temporarily unavailable - the provider connection failed. "
        "No weather values are shown rather than estimated ones."
    ),
    STATE_INVALID_LOCATION: (
        "Location is required to retrieve weather data. Add your district or field "
        "coordinates to receive verified weather."
    ),
    STATE_DATA_STALE: (
        "The provider could not be reached, so the last verified update is shown and "
        "marked as stale rather than presented as current."
    ),
    STATE_CONFIGURATION_ERROR: (
        "A required provider credential is not configured on this deployment, so live "
        "values cannot be retrieved. No value is estimated in its place."
    ),
    STATE_NO_OFFICIAL_RECORD: (
        "The official source returned no record for this crop, district and date."
    ),
    STATE_PROVIDER_ACCESS_GATED: (
        "The official source protects this report behind its own access gate, so AGRIQ "
        "does not retrieve it automatically."
    ),
}

#: State-specific message for the mandi provider when its credential is missing.
#: Names the environment variable but never a value.
MANDI_CREDENTIAL_MESSAGE = (
    "Live mandi prices need a data.gov.in API key on this deployment "
    "(DATA_GOV_IN_API_KEY). Until it is configured AGRIQ shows persisted official "
    "records only, and never an estimated price."
)
#: State-specific message when the official market service itself is failing.
MANDI_SOURCE_ERROR_MESSAGE = (
    "The Government mandi service is temporarily unavailable, so no live price could "
    "be retrieved. No price is estimated in its place."
)
#: State-specific message when the provider answered but had nothing for this query.
MANDI_NO_RECORD_MESSAGE = (
    "No official mandi record was returned for this crop, district and date."
)
#: NOTE: record-age windows are deliberately NOT defined here. Freshness has one
#: owner — ``domain.risk_engine.freshness.classify`` (fresh/aging/stale/expired
#: per input kind) — and a second table in AGRIQ would be a bug waiting to happen.
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
