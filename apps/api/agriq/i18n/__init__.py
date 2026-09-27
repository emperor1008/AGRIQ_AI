"""Centralized internationalization (Phase 7.2).

One translation system for the whole application. Nothing translates strings
inline: backend messages, templates and the browser bundle all resolve keys
against the JSON catalogs in ``locales/``.

Supported languages: English (default), Odia, Hindi.

Honesty rules (these matter more than convenience):

* The catalogs hold **interface** strings only. Authoritative agricultural
  text (technique descriptions, safety notices, label directions) is never
  "translated" here — it lives in the knowledge base with its own
  ``knowledge_translations`` rows and review state.
* Every catalog carries ``_meta.translation_status``. When it is not
  ``native_reviewed`` the interface reports ``TRANSLATION_PENDING_REVIEW`` and
  the UI shows the draft notice, including the English original for
  safety-critical notices. A draft is never presented as a verified
  translation.
* A missing key falls back to English, then to the key itself. It never
  invents text.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

DEFAULT_LANGUAGE = "en"

#: Canonical honest states for an interface catalog.
#: A catalog is only ever reported as reviewed when it explicitly declares
#: ``translation_status: native_reviewed`` — anything else is reported as a
#: draft, so no deployment can accidentally claim an unreviewed translation.
TRANSLATION_PENDING_REVIEW = "TRANSLATION_PENDING_REVIEW"
TRANSLATION_UNAVAILABLE = "TRANSLATION_UNAVAILABLE"
TRANSLATION_SOURCE_LANGUAGE = "source_language"
TRANSLATION_NATIVE_REVIEWED = "native_reviewed"

COOKIE_NAME = "agriq_lang"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365

LANGUAGE_REQUEST_ARG = "lang"


@dataclass(frozen=True)
class Language:
    """One supported language and how it is presented."""

    code: str
    english_name: str
    native_name: str
    html_lang: str
    voice_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "english_name": self.english_name,
            "native_name": self.native_name,
            "html_lang": self.html_lang,
            "voice_code": self.voice_code,
        }


SUPPORTED: dict[str, Language] = {
    "en": Language("en", "English", "English", "en", "en-IN"),
    "or": Language("or", "Odia", "ଓଡ଼ିଆ", "or", "or"),
    "hi": Language("hi", "Hindi", "हिन्दी", "hi", "hi"),
}

#: Near-miss inputs accepted from URLs, cookies, HTTP headers and the existing
#: ``farmer_profiles.preferred_language`` values (e.g. "Odia").
_ALIASES: Mapping[str, str] = {
    "en": "en", "en-in": "en", "en_in": "en", "en-us": "en", "en-gb": "en",
    "english": "en", "eng": "en",
    "or": "or", "or-in": "or", "or_in": "or", "ori": "or", "oriya": "or",
    "odia": "or", "ଓଡ଼ିଆ": "or",
    "hi": "hi", "hi-in": "hi", "hi_in": "hi", "hin": "hi", "hindi": "hi",
    "हिन्दी": "hi", "हिंदी": "hi",
}


def normalise_language(value: Any) -> str:
    """Map any near-miss language value onto a supported code (else default)."""
    if value is None:
        return DEFAULT_LANGUAGE
    candidate = str(value).strip().lower()
    if not candidate:
        return DEFAULT_LANGUAGE
    mapped = _ALIASES.get(candidate)
    if mapped:
        return mapped
    # Accept the leading subtag of a BCP-47 tag ("or-IN" handled above; also
    # tolerate "hi-IN-x-foo").
    head = candidate.split("-")[0].split("_")[0]
    return _ALIASES.get(head, DEFAULT_LANGUAGE)


def is_supported(value: Any) -> bool:
    """True only when ``value`` names a supported language explicitly."""
    if value is None:
        return False
    candidate = str(value).strip().lower()
    return candidate in _ALIASES


def language(code: Any) -> Language:
    return SUPPORTED[normalise_language(code)]


def available_languages() -> list[dict[str, Any]]:
    """Supported languages in switcher order (English first: the default)."""
    return [SUPPORTED[code].to_dict() for code in SUPPORTED]


def catalog_path(code: str) -> Path:
    return LOCALES_DIR / f"{normalise_language(code)}.json"


@lru_cache(maxsize=8)
def catalog(code: str) -> dict[str, Any]:
    """Load one catalog (cached). A missing/corrupt file yields an empty map."""
    path = catalog_path(code)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def catalog_meta(code: str) -> dict[str, Any]:
    meta = catalog(code).get("_meta")
    return meta if isinstance(meta, dict) else {}


def translation_status(code: str) -> str:
    """Review state of an interface catalog (never overclaimed)."""
    normalised = normalise_language(code)
    if normalised == DEFAULT_LANGUAGE:
        # English is the source language of the catalog, not a translation.
        return TRANSLATION_SOURCE_LANGUAGE
    if not catalog(normalised):
        return TRANSLATION_UNAVAILABLE
    declared = str(catalog_meta(normalised).get("translation_status") or "")
    if declared == TRANSLATION_NATIVE_REVIEWED:
        return TRANSLATION_NATIVE_REVIEWED
    return TRANSLATION_PENDING_REVIEW


def is_translation_pending(code: str) -> bool:
    return translation_status(code) == TRANSLATION_PENDING_REVIEW


def _lookup(data: Mapping[str, Any], dotted_key: str) -> Optional[str]:
    node: Any = data
    for part in dotted_key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def _format(text: str, params: Mapping[str, Any]) -> str:
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        # A malformed placeholder must never break a page: show the raw string.
        return text


def translate(key: str, code: Any = DEFAULT_LANGUAGE, **params: Any) -> str:
    """Resolve ``key`` in ``code``, falling back to English, then to ``key``."""
    normalised = normalise_language(code)
    for candidate in (normalised, DEFAULT_LANGUAGE):
        text = _lookup(catalog(candidate), key)
        if text is not None:
            return _format(text, params)
    return key


def translate_many(keys: Iterable[str], code: Any = DEFAULT_LANGUAGE) -> dict[str, str]:
    return {key: translate(key, code) for key in keys}


class Translator:
    """Bound translator: ``t = translator_for("or"); t("common.logout")``."""

    def __init__(self, code: Any = DEFAULT_LANGUAGE) -> None:
        self.code = normalise_language(code)

    def __call__(self, key: str, **params: Any) -> str:
        return translate(key, self.code, **params)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Translator({self.code!r})"


def translator_for(code: Any = DEFAULT_LANGUAGE) -> Translator:
    return Translator(code)


# ---------------------------------------------------------------------------
# Request-scoped resolution
# ---------------------------------------------------------------------------

#: Keys of the catalog subtree shipped to the browser (kept small on purpose:
#: the feature must stay usable on low-bandwidth connections).
BROWSER_PREFIXES = ("js.", "common.", "knowledge.")

#: How many catalog strings may be shipped to the browser in one page load.
MAX_BROWSER_MESSAGES = 400


def browser_messages(code: Any = DEFAULT_LANGUAGE) -> dict[str, str]:
    """The subset of a catalog the browser needs, flattened to dotted keys."""
    normalised = normalise_language(code)
    messages: dict[str, str] = {}

    def walk(node: Mapping[str, Any], prefix: str = "") -> None:
        for key, value in node.items():
            if key == "_meta" or len(messages) >= MAX_BROWSER_MESSAGES:
                continue
            dotted = f"{prefix}{key}"
            if isinstance(value, Mapping):
                walk(value, f"{dotted}.")
            elif isinstance(value, str) and dotted.startswith(BROWSER_PREFIXES):
                messages[dotted] = value

    walk(catalog(DEFAULT_LANGUAGE))
    if normalised != DEFAULT_LANGUAGE:
        walk(catalog(normalised))
    return messages


def resolve_language(
    *,
    requested: Any = None,
    cookie: Any = None,
    profile_value: Any = None,
    accept_language: Any = None,
) -> tuple[str, str]:
    """Pick the effective language and report which source decided it.

    Order: explicit request (``?lang=``) → user's stored preference → cookie →
    ``Accept-Language`` → English. Only *explicitly* supported values are
    honoured; anything else is reported as a fallback, never guessed.
    """
    if is_supported(requested):
        return normalise_language(requested), "request"
    if is_supported(profile_value):
        return normalise_language(profile_value), "profile"
    if is_supported(cookie):
        return normalise_language(cookie), "cookie"
    if accept_language:
        for chunk in str(accept_language).split(","):
            tag = chunk.split(";")[0]
            if is_supported(tag):
                return normalise_language(tag), "accept_language"
    return DEFAULT_LANGUAGE, "default"


def resolve_request_language() -> str:
    """Effective language for the current Flask request (never raises)."""
    try:
        from flask import has_request_context, request, session
    except ImportError:  # pragma: no cover - Flask is always installed here
        return DEFAULT_LANGUAGE
    if not has_request_context():
        return DEFAULT_LANGUAGE

    profile_value = None
    try:
        from ..core.security import current_user
        from ..extensions import db
        from ..models.farmer import FarmerProfile

        user = current_user()
        if user is not None:
            profile = db.session.execute(
                db.select(FarmerProfile).where(FarmerProfile.user_id == user.id)
            ).scalar_one_or_none()
            if profile is not None:
                profile_value = profile.preferred_language
    except Exception:  # noqa: BLE001 - language must never break a request
        profile_value = None

    resolved, _source = resolve_language(
        requested=request.args.get(LANGUAGE_REQUEST_ARG),
        cookie=request.cookies.get(COOKIE_NAME),
        profile_value=profile_value or session.get("agriq_language"),
        accept_language=request.headers.get("Accept-Language"),
    )
    return resolved


def remember_language(response, code: str):
    """Persist an explicit choice on the response (cookie) and the session."""
    if not is_supported(code):
        return response
    normalised = normalise_language(code)
    try:
        from flask import session

        session["agriq_language"] = normalised
    except Exception:  # noqa: BLE001 - never fail a response over a preference
        pass
    response.set_cookie(
        COOKIE_NAME,
        normalised,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="Lax",
        secure=os.environ.get("AGRIQ_COOKIE_SECURE", "").strip() in {"1", "true", "yes"},
        path="/",
    )
    return response


def install_i18n(app) -> None:
    """Register the translator as a Jinja global plus a context processor."""
    from flask import request

    @app.before_request
    def _apply_language_argument():  # pragma: no cover - exercised via routes
        from flask import g

        g.agriq_language = resolve_request_language()
        requested = request.args.get(LANGUAGE_REQUEST_ARG)
        if is_supported(requested):
            g.agriq_language_switch = normalise_language(requested)

    @app.after_request
    def _persist_language(response):  # pragma: no cover - exercised via routes
        from flask import g

        switched = getattr(g, "agriq_language_switch", None)
        if switched:
            return remember_language(response, switched)
        return response

    @app.context_processor
    def _i18n_context():  # pragma: no cover - exercised via routes
        from flask import g

        code = getattr(g, "agriq_language", DEFAULT_LANGUAGE)
        meta = language(code)
        return {
            "t": translator_for(code),
            "language": code,
            "language_meta": meta.to_dict(),
            "languages": available_languages(),
            "ui_translation_status": translation_status(code),
            "browser_messages": browser_messages(code),
        }

    app.jinja_env.globals["t_for"] = translator_for
    app.jinja_env.globals["supported_languages"] = available_languages


__all__ = [
    "DEFAULT_LANGUAGE",
    "TRANSLATION_NATIVE_REVIEWED",
    "TRANSLATION_PENDING_REVIEW",
    "TRANSLATION_SOURCE_LANGUAGE",
    "TRANSLATION_UNAVAILABLE",
    "COOKIE_NAME",
    "COOKIE_MAX_AGE_SECONDS",
    "LANGUAGE_REQUEST_ARG",
    "Language",
    "SUPPORTED",
    "Translator",
    "available_languages",
    "browser_messages",
    "catalog",
    "catalog_meta",
    "install_i18n",
    "is_supported",
    "is_translation_pending",
    "language",
    "normalise_language",
    "remember_language",
    "resolve_language",
    "resolve_request_language",
    "translate",
    "translate_many",
    "translation_status",
    "translator_for",
]
