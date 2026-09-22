"""Application factory (ARC-01).

``create_app()`` assembles configuration, extensions, blueprints and
template/static locations. ``apps/api/app.py`` stays a two-line shim around
this factory, and ``wsgi.py`` is the production Gunicorn target.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from .core.config import get_config
from .core.logging import configure_logging
from .extensions import limiter

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _PACKAGE_DIR / "templates"
#: Frontend assets live in the dedicated web app (apps/web/static).
_STATIC_DIR = _PACKAGE_DIR.parents[1] / "web" / "static"


def create_app(config_object=None) -> Flask:
    """Create and configure the AGRIQ AI Flask application."""
    configure_logging()
    app = Flask(
        "agriq",
        template_folder=str(_TEMPLATE_DIR),
        static_folder=str(_STATIC_DIR),
        static_url_path="/static",
    )

    config = config_object or get_config()
    app.config.from_object(config)
    if config_object is not None:
        # Allow tests to pass any config object (e.g. TestingConfig).
        app.config.from_object(config_object)

    _ensure_instance_path(app)

    # Extensions -----------------------------------------------------------
    limiter.storage_uri = app.config.get("RATELIMIT_STORAGE_URI", "memory://")
    limiter.init_app(app)

    from .extensions import db

    db.init_app(app)

    # Blueprints -----------------------------------------------------------
    from .api import assistant, auth, copilot, dashboard, errors, farmer_data, health, voice, weather

    app.register_blueprint(health.health_bp)
    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(dashboard.dashboard_bp)
    app.register_blueprint(assistant.assistant_bp)
    app.register_blueprint(weather.weather_bp)
    app.register_blueprint(farmer_data.farmer_data_bp)
    app.register_blueprint(copilot.copilot_bp)
    app.register_blueprint(voice.voice_bp)
    app.register_blueprint(errors.errors_bp)

    _apply_rate_limits(app)

    # Database -------------------------------------------------------------
    # Local SQLite convenience only: auto-create the schema. Production
    # PostgreSQL must run the Alembic migrations (run_migrations.py) —
    # never an implicit create_all at boot.
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite"):
        with app.app_context():
            db.create_all()

    # Phase 2/3: per-route limits for the copilot and voice endpoints.
    if limiter.enabled:
        from .api.copilot import post_message
        from .api.voice import ask_copilot as voice_ask, get_transcription, synthesise, upload_audio

        limiter.limit(app.config.get("AGRIQ_RATE_ASSISTANT", "12 per minute"))(post_message)
        limiter.limit(app.config.get("AGRIQ_RATE_VOICE_UPLOAD", "10 per minute"))(upload_audio)
        limiter.limit(app.config.get("AGRIQ_RATE_VOICE_TRANSCRIBE", "10 per minute"))(get_transcription)
        limiter.limit(app.config.get("AGRIQ_RATE_VOICE_TTS", "10 per minute"))(synthesise)
        limiter.limit(app.config.get("AGRIQ_RATE_ASSISTANT", "12 per minute"))(voice_ask)

    return app


def _apply_rate_limits(app: Flask) -> None:
    """Attach documented per-route rate limits (03_SECURITY_AND_ACCESS.md)."""
    from .api.assistant import ask_ai
    from .api.auth import choose_mode, login
    from .api.dashboard import dashboard
    from .api.weather import live_weather_api

    limits = {
        login: app.config.get("AGRIQ_RATE_LOGIN", "8 per minute"),
        choose_mode: app.config.get("AGRIQ_RATE_LOGIN", "8 per minute"),
        dashboard: app.config.get("AGRIQ_RATE_ANALYSIS", "20 per minute"),
        ask_ai: app.config.get("AGRIQ_RATE_ASSISTANT", "12 per minute"),
        live_weather_api: app.config.get("AGRIQ_RATE_WEATHER", "30 per minute"),
    }
    for view, limit in limits.items():
        if not limiter.enabled:  # pragma: no cover - testing mode
            continue
        limiter.limit(limit)(view)


def _ensure_instance_path(app: Flask) -> None:
    os.makedirs(app.instance_path, exist_ok=True)


__all__ = ["create_app"]
