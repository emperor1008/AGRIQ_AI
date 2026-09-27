"""Environment-driven configuration (12-factor; secrets only from environment)."""
from __future__ import annotations

import os
from datetime import timedelta


def _bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


#: Development convenience key. Production refuses to boot with it (§28).
DEV_SECRET_KEY_FALLBACK = "AGRIQ_ai_v3_private_key"
#: Values nobody may use as a production secret, even though they look chosen.
_FORBIDDEN_SECRETS = {
    "secret", "test", "development", "dev", "password", "changeme", "123456",
    "agriq", "agriqai", DEV_SECRET_KEY_FALLBACK,
}


def secret_key_problem(secret: str | None) -> str | None:
    """Return why a secret is unusable, or None when it is acceptable."""
    value = str(secret or "").strip()
    if not value:
        return "AGRIQ_SECRET_KEY is not set."
    if len(value) < 32:
        return "AGRIQ_SECRET_KEY must be at least 32 characters long."
    if value.lower() in _FORBIDDEN_SECRETS:
        return "AGRIQ_SECRET_KEY is a known placeholder value."
    return None


class BaseConfig:
    """Base configuration shared by all environments."""

    def get(self, key: str, default=None):
        """Dict-like access so services can read config without Flask."""
        return getattr(self, key, default)

    #: TestingConfig keeps its deterministic values instead of re-reading the
    #: process environment (a CI runner may export AGRIQ_SECRET_KEY etc.).
    REFRESH_FROM_ENVIRONMENT = True

    def __init__(self) -> None:
        # Re-read environment-dependent values at instantiation so process
        # environment changes (tests, deployments) always apply.
        self.SQLALCHEMY_DATABASE_URI = os.environ.get(
            "DATABASE_URL", self.SQLALCHEMY_DATABASE_URI
        )
        self.RATELIMIT_STORAGE_URI = os.environ.get(
            "RATELIMIT_STORAGE_URI", self.RATELIMIT_STORAGE_URI
        )
        if self.REFRESH_FROM_ENVIRONMENT:
            self._refresh_from_environment()

    def _refresh_from_environment(self) -> None:
        """Re-read environment-driven settings at instantiation time.

        Class attributes are evaluated when the module is first imported, which
        is *before* an entrypoint can load an optional ``.env`` file. Phase 7.1
        moved every secret- and session-bearing setting here so the value that is
        actually used is the value that is actually configured — the class-level
        defaults remain only as documentation of the fallback.
        """
        self.SECRET_KEY = os.environ.get("AGRIQ_SECRET_KEY", self.SECRET_KEY)
        self.SESSION_COOKIE_SECURE = _bool(os.environ.get("AGRIQ_COOKIE_SECURE", "0"))
        self.AGRIQ_ENABLE_HSTS = _bool(os.environ.get("AGRIQ_ENABLE_HSTS", "0"))
        self.AGRIQ_ENABLE_CSRF = _bool(os.environ.get("AGRIQ_ENABLE_CSRF", "1"))
        self.AGRIQ_SESSION_IDLE_TIMEOUT_HOURS = max(
            1, int(os.environ.get("AGRIQ_SESSION_IDLE_TIMEOUT_HOURS", "8"))
        )
        self.AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS = max(
            1, int(os.environ.get("AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS", str(24 * 30)))
        )
        self.AGRIQ_ALLOWED_ORIGINS = [
            origin.strip()
            for origin in os.environ.get("AGRIQ_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ]
        self.AGRIQ_RATE_RECOVERY = os.environ.get("AGRIQ_RATE_RECOVERY", "5 per minute")
        self.AGRIQ_PASSWORD_RESET_TTL_MINUTES = max(
            5, int(os.environ.get("AGRIQ_PASSWORD_RESET_TTL_MINUTES", "30"))
        )
        self.AGRIQ_EMAIL_PROVIDER = os.environ.get("AGRIQ_EMAIL_PROVIDER", "").strip()
        self.AGRIQ_SMTP_HOST = os.environ.get("AGRIQ_SMTP_HOST", "").strip()
        self.AGRIQ_SMTP_PORT = int(os.environ.get("AGRIQ_SMTP_PORT", "587"))
        self.AGRIQ_SMTP_USERNAME = os.environ.get("AGRIQ_SMTP_USERNAME", "").strip()
        self.AGRIQ_SMTP_PASSWORD = os.environ.get("AGRIQ_SMTP_PASSWORD", "")
        self.AGRIQ_SMTP_USE_TLS = os.environ.get("AGRIQ_SMTP_USE_TLS", "1")
        self.AGRIQ_EMAIL_FROM = os.environ.get("AGRIQ_EMAIL_FROM", "").strip()
        self.AGRIQ_PUBLIC_BASE_URL = os.environ.get("AGRIQ_PUBLIC_BASE_URL", "").strip()

    ENV = "development"
    DEBUG = False
    TESTING = False

    SECRET_KEY = os.environ.get("AGRIQ_SECRET_KEY", DEV_SECRET_KEY_FALLBACK)
    SESSION_COOKIE_NAME = "agriq_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    #: Secure cookies require HTTPS; controlled via AGRIQ_COOKIE_SECURE.
    SESSION_COOKIE_SECURE = _bool(os.environ.get("AGRIQ_COOKIE_SECURE", "0"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Phase 7.1 session lifetimes. The idle window is refreshed by activity; the
    # absolute cap can never be extended, so a stolen cookie dies regardless.
    AGRIQ_SESSION_IDLE_TIMEOUT_HOURS = max(
        1, int(os.environ.get("AGRIQ_SESSION_IDLE_TIMEOUT_HOURS", "8"))
    )
    AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS = max(
        1, int(os.environ.get("AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS", str(24 * 30)))
    )

    #: Origins allowed to make state-changing requests. Empty = same origin only
    #: (AGRIQ serves its own frontend). "*" is never accepted.
    AGRIQ_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("AGRIQ_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]

    # Phase 7.1 recovery limits + email provider (all optional; when absent the
    # recovery endpoints report an honest unavailable state instead of faking a send).
    AGRIQ_RATE_RECOVERY = os.environ.get("AGRIQ_RATE_RECOVERY", "5 per minute")
    AGRIQ_PASSWORD_RESET_TTL_MINUTES = max(
        5, int(os.environ.get("AGRIQ_PASSWORD_RESET_TTL_MINUTES", "30"))
    )
    AGRIQ_EMAIL_PROVIDER = os.environ.get("AGRIQ_EMAIL_PROVIDER", "").strip()
    AGRIQ_SMTP_HOST = os.environ.get("AGRIQ_SMTP_HOST", "").strip()
    AGRIQ_SMTP_PORT = int(os.environ.get("AGRIQ_SMTP_PORT", "587"))
    AGRIQ_SMTP_USERNAME = os.environ.get("AGRIQ_SMTP_USERNAME", "").strip()
    AGRIQ_SMTP_PASSWORD = os.environ.get("AGRIQ_SMTP_PASSWORD", "")
    AGRIQ_SMTP_USE_TLS = os.environ.get("AGRIQ_SMTP_USE_TLS", "1")
    AGRIQ_EMAIL_FROM = os.environ.get("AGRIQ_EMAIL_FROM", "").strip()
    AGRIQ_PUBLIC_BASE_URL = os.environ.get("AGRIQ_PUBLIC_BASE_URL", "").strip()

    #: HSTS is only enabled when the app is served over HTTPS.
    AGRIQ_ENABLE_HSTS = _bool(os.environ.get("AGRIQ_ENABLE_HSTS", "0"))
    #: CSRF protection toggle for state-changing routes (on by default).
    AGRIQ_ENABLE_CSRF = _bool(os.environ.get("AGRIQ_ENABLE_CSRF", "1"))

    # Optional Gemini generative AI.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "30"))

    # Phase 2 copilot settings.
    COPILOT_MAX_CONTEXT_TOKENS = int(os.environ.get("COPILOT_MAX_CONTEXT_TOKENS", "4000"))
    KNOWLEDGE_STORAGE_PATH = os.environ.get("KNOWLEDGE_STORAGE_PATH", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "knowledge",
    )
    KNOWLEDGE_MIN_RELEVANCE_SCORE = float(os.environ.get("KNOWLEDGE_MIN_RELEVANCE_SCORE", "0.18"))
    WEATHER_CACHE_TTL_SECONDS = int(os.environ.get("WEATHER_CACHE_TTL_SECONDS", "1800"))

    # Phase 3 voice settings. All providers are opt-in; without configuration
    # the voice layer reports honest unavailable states and text keeps working.
    VOICE_ASR_PROVIDER = os.environ.get("VOICE_ASR_PROVIDER", "").strip()
    VOICE_TTS_PROVIDER = os.environ.get("VOICE_TTS_PROVIDER", "").strip()
    VOICE_TRANSLATION_PROVIDER = os.environ.get("VOICE_TRANSLATION_PROVIDER", "").strip()

    BHASHINI_API_KEY = os.environ.get("BHASHINI_API_KEY", "").strip()
    BHASHINI_USER_ID = os.environ.get("BHASHINI_USER_ID", "").strip()
    BHASHINI_PIPELINE_ID = os.environ.get("BHASHINI_PIPELINE_ID", "").strip()
    BHASHINI_BASE_URL = os.environ.get("BHASHINI_BASE_URL", "").strip()

    VOICE_MAX_FILE_SIZE_MB = int(os.environ.get("VOICE_MAX_FILE_SIZE_MB", "10"))
    VOICE_MAX_DURATION_SECONDS = int(os.environ.get("VOICE_MAX_DURATION_SECONDS", "60"))
    VOICE_MIN_DURATION_SECONDS = float(os.environ.get("VOICE_MIN_DURATION_SECONDS", "0.5"))
    VOICE_AUDIO_RETENTION_HOURS = int(os.environ.get("VOICE_AUDIO_RETENTION_HOURS", "0"))
    VOICE_TEMP_STORAGE_PATH = os.environ.get("VOICE_TEMP_STORAGE_PATH", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "voice_audio",
    )
    VOICE_PROVIDER_TIMEOUT_SECONDS = int(os.environ.get("VOICE_PROVIDER_TIMEOUT_SECONDS", "30"))
    VOICE_QUEUE_MAX_RETRIES = int(os.environ.get("VOICE_QUEUE_MAX_RETRIES", "3"))

    # Market (AGMARKNET via data.gov.in). Without a key the market feed is
    # reported as unavailable; no prices are ever generated locally.
    DATA_GOV_IN_API_KEY = os.environ.get("DATA_GOV_IN_API_KEY", "").strip()
    DATA_GOV_IN_MARKET_RESOURCE_ID = os.environ.get(
        "DATA_GOV_IN_MARKET_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070"
    ).strip()

    # Phase 5 crop risk intelligence. The TTL is the idempotency window for a
    # stored analysis run: re-analysing a field inside it returns the stored
    # result instead of recomputing (and never re-alerts on identical results).
    RISK_ASSESSMENT_TTL_MINUTES = max(1, int(os.environ.get("RISK_ASSESSMENT_TTL_MINUTES", "30")))

    # Phase 4 crop-image intelligence. The feature is available only when a
    # registry-approved model exists; otherwise it reports an honest
    # unavailable state. Images are stored privately (never public URLs).
    IMAGE_MAX_FILE_SIZE_MB = int(os.environ.get("IMAGE_MAX_FILE_SIZE_MB", "5"))
    IMAGE_MAX_DIMENSION = int(os.environ.get("IMAGE_MAX_DIMENSION", "6000"))
    IMAGE_STORAGE_PATH = os.environ.get("IMAGE_STORAGE_PATH", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "image_store",
    )
    IMAGE_DECODER_TIMEOUT_SECONDS = int(os.environ.get("IMAGE_DECODER_TIMEOUT_SECONDS", "10"))
    IMAGE_MAX_PER_REQUEST = int(os.environ.get("IMAGE_MAX_PER_REQUEST", "1"))
    IMAGE_REGISTRY_PATH = os.environ.get("IMAGE_REGISTRY_PATH", "")  # default: ml/models/registry.yaml

    # Uploads (soil reports, observation images) live outside the source tree.
    AGRIQ_UPLOAD_FOLDER = os.environ.get("AGRIQ_UPLOAD_FOLDER", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads",
    )
    #: Hard request-size ceiling for all routes (multipart included).
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MiB

    # Rate limiter backend. Production must use Redis.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = []
    RATELIMIT_ENABLED = True

    # External-data freshness (seconds). Snapshots older than this are re-fetched;
    # the UI always shows the stored retrieval time either way.
    WEATHER_SNAPSHOT_TTL_SECONDS = int(os.environ.get("WEATHER_SNAPSHOT_TTL_SECONDS", "1800"))
    MARKET_SNAPSHOT_TTL_SECONDS = int(os.environ.get("MARKET_SNAPSHOT_TTL_SECONDS", "21600"))

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///agriq.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(BaseConfig):
    ENV = "development"
    DEBUG = _bool(os.environ.get("FLASK_DEBUG", "1"))


class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False

    def __init__(self) -> None:  # pragma: no cover - guard rail only
        super().__init__()
        database = os.environ.get("DATABASE_URL", "")
        if not database or database.startswith("sqlite"):
            raise RuntimeError(
                "Production requires a PostgreSQL DATABASE_URL (AGRIQ production "
                "does not run on SQLite)."
            )
        storage = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
        if storage.startswith("memory"):
            raise RuntimeError(
                "Production requires Redis for RATELIMIT_STORAGE_URI "
                "(e.g. redis://redis:6379/0)."
            )
        problem = secret_key_problem(os.environ.get("AGRIQ_SECRET_KEY"))
        if problem:
            raise RuntimeError(f"Unusable production AGRIQ_SECRET_KEY: {problem}")
        if "*" in self.AGRIQ_ALLOWED_ORIGINS:
            raise RuntimeError(
                "AGRIQ_ALLOWED_ORIGINS must list explicit origins; '*' is not allowed "
                "with credentialed sessions."
            )
        # Sessions must not outlive their absolute cap, and cookies that carry
        # them must be HTTPS-only in production.
        if self.AGRIQ_SESSION_IDLE_TIMEOUT_HOURS > self.AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS:
            raise RuntimeError(
                "AGRIQ_SESSION_IDLE_TIMEOUT_HOURS cannot exceed "
                "AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS."
            )
        if not self.SESSION_COOKIE_SECURE:
            raise RuntimeError(
                "Production requires AGRIQ_COOKIE_SECURE=1 (session cookies must be "
                "HTTPS-only)."
            )
        if self.AGRIQ_EMAIL_PROVIDER and not (self.AGRIQ_SMTP_HOST and (self.AGRIQ_EMAIL_FROM or self.AGRIQ_SMTP_USERNAME)):
            raise RuntimeError(
                "AGRIQ_EMAIL_PROVIDER is set but SMTP host/sender is missing. Either "
                "configure email delivery fully or leave the provider unset (password "
                "recovery will report PASSWORD_RESET_EMAIL_UNAVAILABLE honestly)."
            )


class TestingConfig(BaseConfig):
    #: Not a test class — stop pytest from collecting this config object.
    __test__ = False
    #: Deterministic values win; the suite must not inherit a runner's secrets or
    #: session settings.
    REFRESH_FROM_ENVIRONMENT = False

    TESTING = True
    ENV = "testing"
    # Deterministic secret for tests; never used in production.
    SECRET_KEY = "test-secret-key-not-for-production"
    # Isolated in-memory database: the suite must NEVER touch the dev/prod
    # database file (a create_all/drop_all cycle here once wiped agriq.db).
    # Migration tests override DATABASE_URL explicitly to temp files.
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    # Test uploads go to a throwaway directory inside the test tree.
    AGRIQ_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "_test_uploads")
    VOICE_TEMP_STORAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "_test_voice_audio")
    IMAGE_STORAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "_test_image_store")


CONFIG_BY_ENV: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config() -> BaseConfig:
    """Resolve the config class from AGRIQ_ENV (default: development)."""
    env = os.environ.get("AGRIQ_ENV", "development").strip().lower()
    config_cls = CONFIG_BY_ENV.get(env, DevelopmentConfig)
    return config_cls()


__all__ = [
    "BaseConfig",
    "DevelopmentConfig",
    "ProductionConfig",
    "TestingConfig",
    "CONFIG_BY_ENV",
    "get_config",
]
