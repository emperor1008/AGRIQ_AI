"""Unit tests for the centralized i18n system (Phase 7.2)."""
from __future__ import annotations

import json
from pathlib import Path

from agriq import i18n


def test_supported_languages_are_english_odia_hindi():
    codes = [item["code"] for item in i18n.available_languages()]
    assert codes == ["en", "or", "hi"]
    assert i18n.DEFAULT_LANGUAGE == "en"


def test_catalogs_are_valid_json_and_cover_the_same_keys():
    def flatten(node, prefix=""):
        keys = set()
        for key, value in node.items():
            if key == "_meta":
                continue
            dotted = f"{prefix}{key}"
            if isinstance(value, dict):
                keys |= flatten(value, f"{dotted}.")
            else:
                keys.add(dotted)
        return keys

    english = flatten(i18n.catalog("en"))
    assert english
    for code in ("or", "hi"):
        other = flatten(i18n.catalog(code))
        missing = english - other
        extra = other - english
        assert not missing, f"{code} is missing keys: {sorted(missing)[:10]}"
        assert not extra, f"{code} has keys English does not: {sorted(extra)[:10]}"


def test_no_catalog_value_is_empty():
    for code in ("en", "or", "hi"):
        payload = json.loads((Path(i18n.LOCALES_DIR) / f"{code}.json").read_text(encoding="utf-8"))
        for section, value in payload.items():
            if section == "_meta":
                continue
            assert value, f"{code}.{section} is empty"
            for key, text in value.items():
                assert isinstance(text, str) and text.strip(), f"{code}.{section}.{key} is empty"


def test_language_normalisation_accepts_real_world_values():
    assert i18n.normalise_language("Odia") == "or"          # farmer profile value
    assert i18n.normalise_language("or-IN") == "or"
    assert i18n.normalise_language("hi_IN") == "hi"
    assert i18n.normalise_language("en-IN") == "en"
    assert i18n.normalise_language("ଓଡ଼ିଆ") == "or"
    assert i18n.normalise_language("de") == "en"            # unsupported → default
    assert i18n.normalise_language(None) == "en"
    assert i18n.normalise_language("") == "en"


def test_is_supported_only_for_explicit_languages():
    assert i18n.is_supported("hi")
    assert i18n.is_supported("Odia")
    assert not i18n.is_supported("de")
    assert not i18n.is_supported(None)


def test_resolution_order_is_request_then_profile_then_cookie_then_header():
    assert i18n.resolve_language(requested="hi", profile_value="Odia",
                                 cookie="or") == ("hi", "request")
    assert i18n.resolve_language(requested="de", profile_value="Odia",
                                 cookie="or") == ("or", "profile")
    assert i18n.resolve_language(cookie="hi") == ("hi", "cookie")
    assert i18n.resolve_language(accept_language="or-IN,or;q=0.9,en;q=0.8") == ("or", "accept_language")
    assert i18n.resolve_language(accept_language="de-DE") == ("en", "default")


def test_unknown_key_returns_the_key_never_blank_text():
    assert i18n.translate("nope.not.here", "en") == "nope.not.here"
    assert i18n.translate("common.logout", "hi") == "लॉग आउट"


def test_missing_translation_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(i18n, "catalog", lambda code: ({"common": {"only_english": "Only English"}}
                                                      if code == "hi" else i18n.catalog.__wrapped__(code)))
    assert i18n.translate("common.only_english", "hi") == "Only English"


def test_placeholders_are_formatted_and_bad_placeholders_do_not_crash():
    assert i18n.translate("common.result_count", "en", count=3) == "3 verified entry/entries"
    assert i18n.translate("js.results_found", "hi", count=2) == "2 प्रविष्टि मिलीं"


def test_translation_status_reports_drafts_honestly():
    assert i18n.translation_status("en") == "source_language"
    assert i18n.translation_status("or") == i18n.TRANSLATION_PENDING_REVIEW
    assert i18n.translation_status("hi") == i18n.TRANSLATION_PENDING_REVIEW
    assert i18n.is_translation_pending("hi")


def test_browser_messages_are_scoped_and_bounded():
    messages = i18n.browser_messages("hi")
    assert messages, "expected a browser bundle"
    assert all(key.startswith(i18n.BROWSER_PREFIXES) for key in messages)
    assert len(messages) <= i18n.MAX_BROWSER_MESSAGES
    # Interface strings only: knowledge-state wording is included, source text
    # (which never lives in a catalog) obviously is not.
    assert "js.loading" in messages
    assert messages["js.loading"] == i18n.translate("js.loading", "hi")


def test_translator_is_callable_and_reports_its_language():
    translator = i18n.translator_for("Odia")
    assert translator.code == "or"
    assert translator("common.dashboard") == i18n.translate("common.dashboard", "or")
