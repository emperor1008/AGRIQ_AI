"""Environment-driven configuration (12-factor; secrets only from environment)."""
from __future__ import annotations

import os
from datetime import timedelta


def _bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    """Base configuration shared by all environments."""

    def get(self, key: str, default=None):
        """Dict-like access so services can read config without Flask."""
        return getattr(self, key, default)

    def __init__(self) -> None:
        # Re-read environment-dependent values at instantiation so process
        # environment changes (tests, deployments) always apply.
        self.SQLALCHEMY_DATABASE_URI = os.environ.get(
            "DATABASE_URL", self.SQLALCHEMY_DATABASE_URI
        )
        self.RATELIMIT_STORAGE_URI = os.environ.get(
            "RATELIMIT_STORAGE_URI", self.RATELIMIT_STORAGE_URI
        )

    ENV = "development"
    DEBUG = False
    TESTING = False

    SECRET_KEY = os.environ.get("AGRIQ_SECRET_KEY", "AGRIQ_ai_v3_private_key")
    SESSION_COOKIE_NAME = "agriq_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    #: Secure cookies require HTTPS; controlled via AGRIQ_COOKIE_SECURE.
    SESSION_COOKIE_SECURE = _bool(os.environ.get("AGRIQ_COOKIE_SECURE", "0"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

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

    @staticmethod
    def _required_env() -> list[str]:
        missing = []
        if not os.environ.get("AGRIQ_SECRET_KEY"):
            missing.append("AGRIQ_SECRET_KEY")
        return missing

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
        missing = self._required_env()
        if missing:
            raise RuntimeError(f"Missing required production env vars: {', '.join(missing)}")


class TestingConfig(BaseConfig):
    #: Not a test class — stop pytest from collecting this config object.
    __test__ = False

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
