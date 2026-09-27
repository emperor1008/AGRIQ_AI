"""Application factory (ARC-01).

``create_app()`` assembles configuration, extensions, blueprints and
template/static locations. ``apps/api/app.py`` stays a two-line shim around
this factory, and ``wsgi.py`` is the production Gunicorn target.
"""
from __future__ import annotations

import logging
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
    _warn_about_insecure_config(app)

    # Extensions -----------------------------------------------------------
    limiter.storage_uri = app.config.get("RATELIMIT_STORAGE_URI", "memory://")
    limiter.init_app(app)

    from .extensions import db

    db.init_app(app)

    # Internationalization (Phase 7.2) --------------------------------------
    # One translator for backend messages, templates and the browser bundle.
    # Registered before the blueprints so every view and template resolves
    # ``t()``/``language`` from the same request-scoped resolution.
    from .i18n import install_i18n

    install_i18n(app)

    # Blueprints -----------------------------------------------------------
    from .api import (
        assistant, auth, copilot, dashboard, errors, farmer_data, health, images,
        knowledge, market_intel, recovery, risk, sessions, voice, weather,
    )

    app.register_blueprint(health.health_bp)
    app.register_blueprint(auth.auth_bp)
    # Phase 7.1: real password recovery + session/credential management.
    app.register_blueprint(recovery.recovery_bp)
    app.register_blueprint(sessions.sessions_bp)
    app.register_blueprint(dashboard.dashboard_bp)
    app.register_blueprint(assistant.assistant_bp)
    app.register_blueprint(weather.weather_bp)
    app.register_blueprint(farmer_data.farmer_data_bp)
    app.register_blueprint(copilot.copilot_bp)
    app.register_blueprint(voice.voice_bp)
    app.register_blueprint(images.image_bp)
    app.register_blueprint(risk.risk_bp)
    app.register_blueprint(market_intel.market_bp)
    # Phase 7.2: Farming Techniques (verified agricultural knowledge).
    app.register_blueprint(knowledge.knowledge_bp)
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
        from .api.risk import analyze as risk_analyze

        limiter.limit(app.config.get("AGRIQ_RATE_ANALYSIS", "20 per minute"))(risk_analyze)

        # Phase 6: market intelligence shares the analysis budget (reads reuse
        # cached provider payloads; decision endpoints do real work).
        from .api.market_intel import (
            get_forecast as market_forecast,
            get_overview as market_overview,
            post_crop_options as market_crop_options,
            post_logistics as market_logistics,
            post_sell_hold as market_sell_hold,
        )

        market_limit = app.config.get("AGRIQ_RATE_ANALYSIS", "20 per minute")
        for view in (market_overview, market_forecast, market_crop_options,
                     market_sell_hold, market_logistics):
            limiter.limit(market_limit)(view)

    return app


def _apply_rate_limits(app: Flask) -> None:
    """Attach documented per-route rate limits (03_SECURITY_AND_ACCESS.md)."""
    from .api.assistant import ask_ai
    from .api.auth import choose_mode, login
    from .api.dashboard import dashboard
    from .api.knowledge import index_page as knowledge_index, search_api as knowledge_search
    from .api.recovery import forgot_password, reset_password
    from .api.weather import live_weather_api

    limits = {
        # Sign-in and registration share one budget per client address.
        login: app.config.get("AGRIQ_RATE_LOGIN", "8 per minute"),
        choose_mode: app.config.get("AGRIQ_RATE_LOGIN", "8 per minute"),
        # Recovery is deliberately tighter: it triggers outbound email.
        forgot_password: app.config.get("AGRIQ_RATE_RECOVERY", "5 per minute"),
        reset_password: app.config.get("AGRIQ_RATE_RECOVERY", "5 per minute"),
        dashboard: app.config.get("AGRIQ_RATE_ANALYSIS", "20 per minute"),
        ask_ai: app.config.get("AGRIQ_RATE_ASSISTANT", "12 per minute"),
        live_weather_api: app.config.get("AGRIQ_RATE_WEATHER", "30 per minute"),
        # Phase 7.2: knowledge reads are cheap and cacheable, but still bounded
        # so a scraper cannot walk the whole knowledge base from one address.
        knowledge_index: app.config.get("AGRIQ_RATE_KNOWLEDGE", "60 per minute"),
        knowledge_search: app.config.get("AGRIQ_RATE_KNOWLEDGE", "60 per minute"),
    }
    for view, limit in limits.items():
        if not limiter.enabled:  # pragma: no cover - testing mode
            continue
        limiter.limit(limit)(view)


def _warn_about_insecure_config(app: Flask) -> None:
    """Log configuration traps that look exactly like "login is broken".

    Phase 7.1 is about real, diagnosable authentication. Two misconfigurations
    silently break sign-in rather than failing loudly, so they are reported at
    startup (never with values, only with the variable name):

    * a ``Secure`` session cookie served over plain HTTP is never stored by the
      browser, so the user signs in successfully and is bounced straight back;
    * the built-in development secret means every session cookie is signed with
      a value that is public in the source tree.
    """
    from .core.config import DEV_SECRET_KEY_FALLBACK

    logger = logging.getLogger("agriq.app_factory")
    if app.config.get("SESSION_COOKIE_SECURE") and app.config.get("ENV") != "production":
        logger.warning(
            "AGRIQ_COOKIE_SECURE=1 outside production: browsers will not store the "
            "session cookie over plain HTTP, which looks like a failed login. Serve "
            "HTTPS or set AGRIQ_COOKIE_SECURE=0 for local development."
        )
    if app.config.get("SECRET_KEY") == DEV_SECRET_KEY_FALLBACK:
        logger.warning(
            "AGRIQ_SECRET_KEY is the built-in development fallback. Set a real "
            "32+ character secret before exposing this instance to anyone."
        )


def _ensure_instance_path(app: Flask) -> None:
    os.makedirs(app.instance_path, exist_ok=True)


__all__ = ["create_app"]
