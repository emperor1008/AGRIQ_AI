"""Farming Techniques routes (Phase 7.2).

Two surfaces over one service, exactly like the rest of AGRIQ:

* the pages a person uses — ``/farming-techniques`` and its detail pages;
* the versioned JSON API — ``/api/v1/farming-techniques/*``.

Route bodies do HTTP only: authenticate, parse, delegate to
``services.farming_knowledge``, serialise. Every JSON route requires an active
session (the knowledge base lives behind sign-in like the dashboard) and is
read-only: there is deliberately **no** HTTP write path into the knowledge
base, so no route can insert agricultural content. Ingestion is CLI-only.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from ..core.constants import MODE_FARMER, MODE_STUDENT, SESSION_MODE_KEY, SESSION_USER_KEY
from ..core.logging import get_logger
from ..core.security import current_user, get_csrf_token, get_current_user
from ..i18n import (
    is_supported,
    normalise_language,
    resolve_request_language,
    translate,
    translation_status,
)
from ..repositories.farmer_repository import (
    CropCycleRepository,
    FarmRepository,
    FieldRepository,
    ProfileRepository,
)
from ..services import farming_knowledge

logger = get_logger("api.knowledge")

knowledge_bp = Blueprint("knowledge", __name__)

_REQUESTED_LANGUAGE = "lang"


def _require_user():
    """Active session or ``AuthRequiredError`` → 401 ``AUTH_UNAUTHORIZED``.

    One gate for every route in this module, delegating to the single
    authentication dependency (Phase 7.1 §19).
    """
    return get_current_user()


def _language() -> str:
    requested = request.args.get(_REQUESTED_LANGUAGE)
    if is_supported(requested):
        return normalise_language(requested)
    return resolve_request_language()


def _view_mode() -> str:
    mode = session.get(SESSION_MODE_KEY, MODE_FARMER)
    return farming_knowledge.MODE_STUDENT_VIEW if mode == MODE_STUDENT else farming_knowledge.MODE_FARMER_VIEW


def _int_arg(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _farmer_crop_hint() -> str | None:
    """The signed-in farmer's registered crop — used **only** as a filter hint.

    AGRIQ never turns "this technique exists" into "you should use it" (§14):
    the crop pre-fills a filter the user can clear, and the listing says so in
    ``context_note``. Nothing is recommended because of this value.
    """
    user = current_user()
    if user is None:
        return None
    try:
        profile = ProfileRepository.get_for_user(user.id)
        if profile is None:
            return None
        farms = FarmRepository.list_for_profile(profile.id)
        if not farms:
            return None
        fields = FieldRepository.list_for_farm(farms[0].id)
        if not fields:
            return None
        cycle = CropCycleRepository.active_cycle_for_field(fields[0].id)
        crop = getattr(cycle, "crop", None)
        return str(crop) if crop else None
    except Exception:  # noqa: BLE001 - a filter hint must never break the page
        logger.info("farmer_crop_hint_unavailable", exc_info=False)
        return None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@knowledge_bp.get("/farming-techniques")
def index_page():
    """Farming Techniques home: categories, search and the first page of results."""
    if current_user() is None:
        return redirect(url_for("auth.index"))

    language = _language()
    view_mode = _view_mode()
    category = (request.args.get("category") or "").strip().lower() or None
    query = (request.args.get("q") or "").strip() or None
    crop = (request.args.get("crop") or "").strip() or None
    region = (request.args.get("region") or "").strip() or None
    evidence = (request.args.get("evidence") or "").strip() or None
    page = _int_arg("page", 1, minimum=1, maximum=500)

    overview = farming_knowledge.categories_overview()
    facet_data = farming_knowledge.facets()
    listing = farming_knowledge.list_entries(
        language=language, category=category, crop=crop, region=region,
        evidence=evidence, query=query, page=page, mode=view_mode,
    )
    return render_template(
        "knowledge/index.html",
        page="knowledge",
        user_mode=session.get(SESSION_MODE_KEY, MODE_FARMER),
        user_contact=session.get(SESSION_USER_KEY),
        csrf_token=get_csrf_token(),
        categories=overview["categories"],
        overview=overview,
        facets=facet_data,
        listing=listing,
        knowledge_status=farming_knowledge.knowledge_status(),
        selected={"category": category, "q": query, "crop": crop,
                  "region": region, "evidence": evidence, "page": page},
        language=language,
        ui_translation_status=translation_status(language),
        mode=view_mode,
        engine_mode="Farming Techniques",
    )


@knowledge_bp.get("/farming-techniques/partials/results")
def results_partial():
    """Server-rendered results fragment for the in-page search/filter refresh.

    The browser replaces the region with *this* markup, so a scripted refresh
    and a full page load can never drift apart, and no knowledge card is ever
    composed client-side.
    """
    if current_user() is None:
        return "", 401
    language = _language()
    listing = farming_knowledge.list_entries(
        language=language,
        category=(request.args.get("category") or "").strip().lower() or None,
        crop=(request.args.get("crop") or "").strip() or None,
        region=(request.args.get("region") or "").strip() or None,
        evidence=(request.args.get("evidence") or "").strip() or None,
        query=(request.args.get("q") or "").strip() or None,
        page=_int_arg("page", 1, minimum=1, maximum=500),
        page_size=_int_arg("page_size", farming_knowledge.DEFAULT_PAGE_SIZE, minimum=1,
                           maximum=farming_knowledge.MAX_PAGE_SIZE),
        mode=_view_mode(),
    )
    return render_template(
        "knowledge/_results.html",
        listing=listing,
        language=language,
    )


def _render_detail(kind: str, slug: str):
    """Shared detail-page rendering for techniques and pesticide records."""
    language = _language()
    detail = farming_knowledge.entry_detail(
        kind, slug, language=language, mode=_view_mode()
    )
    context = {
        "page": "knowledge",
        "user_mode": session.get(SESSION_MODE_KEY, MODE_FARMER),
        "user_contact": session.get(SESSION_USER_KEY),
        "csrf_token": get_csrf_token(),
        "language": language,
        "detail": detail,
        "mode": _view_mode(),
        "engine_mode": "Farming Techniques",
    }
    if detail is None:
        # A pending/rejected record is indistinguishable from a missing one.
        return render_template("knowledge/detail.html", **context), 404
    return render_template("knowledge/detail.html", **context)


@knowledge_bp.get("/farming-techniques/technique/<slug>")
def technique_page(slug: str):
    if current_user() is None:
        return redirect(url_for("auth.index"))
    return _render_detail("technique", slug)


@knowledge_bp.get("/farming-techniques/pesticide/<slug>")
def pesticide_page(slug: str):
    if current_user() is None:
        return redirect(url_for("auth.index"))
    return _render_detail("pesticide", slug)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@knowledge_bp.get("/api/v1/farming-techniques")
def list_api():
    """Paginated, filterable listing of review-verified records only."""
    _require_user()
    listing = farming_knowledge.list_entries(
        language=_language(),
        category=(request.args.get("category") or "").strip().lower() or None,
        crop=(request.args.get("crop") or "").strip() or None,
        region=(request.args.get("region") or "").strip() or None,
        evidence=(request.args.get("evidence") or "").strip() or None,
        query=(request.args.get("q") or "").strip() or None,
        page=_int_arg("page", 1, minimum=1, maximum=500),
        page_size=_int_arg("page_size", farming_knowledge.DEFAULT_PAGE_SIZE, minimum=1,
                           maximum=farming_knowledge.MAX_PAGE_SIZE),
        mode=_view_mode(),
    )
    return jsonify(listing)


@knowledge_bp.get("/api/v1/farming-techniques/search")
def search_api():
    """Search across verified records; an empty result is a stated state."""
    _require_user()
    term = (request.args.get("q") or "").strip()
    listing = farming_knowledge.list_entries(
        language=_language(),
        category=(request.args.get("category") or "").strip().lower() or None,
        crop=(request.args.get("crop") or "").strip() or None,
        region=(request.args.get("region") or "").strip() or None,
        evidence=(request.args.get("evidence") or "").strip() or None,
        query=term or None,
        page=_int_arg("page", 1, minimum=1, maximum=500),
        page_size=_int_arg("page_size", farming_knowledge.DEFAULT_PAGE_SIZE, minimum=1,
                           maximum=farming_knowledge.MAX_PAGE_SIZE),
        mode=_view_mode(),
    )
    listing["query"] = term
    return jsonify(listing)


@knowledge_bp.get("/api/v1/farming-techniques/categories")
def categories_api():
    _require_user()
    payload = farming_knowledge.categories_overview()
    payload["facets"] = farming_knowledge.facets()
    payload["status_summary"] = farming_knowledge.knowledge_status()
    return jsonify(payload)


@knowledge_bp.get("/api/v1/farming-techniques/crops")
def crops_api():
    _require_user()
    facet_data = farming_knowledge.facets()
    return jsonify({
        "ok": True,
        "crops": facet_data["crops"],
        "state": "OK" if facet_data["crops"] else farming_knowledge.TOKEN_DATA_UNAVAILABLE,
    })


@knowledge_bp.get("/api/v1/farming-techniques/regions")
def regions_api():
    _require_user()
    facet_data = farming_knowledge.facets()
    return jsonify({
        "ok": True,
        "regions": facet_data["regions"],
        "note": translate("knowledge.region_notice", _language()),
        "state": "OK" if facet_data["regions"] else farming_knowledge.TOKEN_DATA_UNAVAILABLE,
    })


@knowledge_bp.get("/api/v1/farming-techniques/evidence-levels")
def evidence_api():
    _require_user()
    return jsonify({"ok": True, "evidence_levels": list(farming_knowledge.EVIDENCE_LEVELS)})


@knowledge_bp.get("/api/v1/farming-techniques/sources")
def sources_api():
    _require_user()
    return jsonify(farming_knowledge.source_index(language=_language()))


@knowledge_bp.get("/api/v1/farming-techniques/status")
def status_api():
    """Honest count of verified vs pending knowledge on this deployment."""
    _require_user()
    payload = farming_knowledge.knowledge_status()
    payload["ui_translation_status"] = translation_status(_language())
    return jsonify(payload)


@knowledge_bp.get("/api/v1/farming-techniques/<kind>/<slug>")
def detail_api(kind: str, slug: str):
    """Detail for one verified technique or pesticide record."""
    _require_user()
    if kind not in {"technique", "pesticide"}:
        return jsonify({
            "ok": False,
            "code": "KNOWLEDGE_VALIDATION",
            "error": "Unknown knowledge record type.",
        }), 400
    detail = farming_knowledge.entry_detail(
        kind, slug, language=_language(), mode=_view_mode()
    )
    if detail is None:
        return jsonify({
            "ok": False,
            "code": "NOT_FOUND",
            "error": translate("common.not_found", _language()),
        }), 404
    return jsonify(detail)


@knowledge_bp.post("/api/v1/farming-techniques/ask")
def ask_api():
    """Retrieval-grounded answer surface for the knowledge base.

    This route deliberately does **not** call a language model. It returns the
    review-verified passages an AI would be allowed to use, together with the
    canonical safety states, so a client cannot present generated agricultural
    text as verified knowledge. When nothing verified matches, the response is
    ``DATA_UNAVAILABLE`` — never invented content.
    """
    _require_user()
    payload = request.get_json(silent=True) or request.form or {}
    question = str(payload.get("question") or "").strip()
    language = _language()
    if not question:
        return jsonify({
            "ok": False,
            "code": "KNOWLEDGE_VALIDATION",
            "error": "A question is required.",
        }), 400
    if len(question) > 2000:
        return jsonify({
            "ok": False,
            "code": "KNOWLEDGE_VALIDATION",
            "error": "Question is too long.",
        }), 400

    from ..services import knowledge_safety  # local import: keeps route module thin

    safety = knowledge_safety.check_knowledge_request(
        question,
        language=language,
        field_area_known=bool(_farmer_crop_hint()),
    )
    if safety.blocked:
        return jsonify({
            "ok": True,
            "status": safety.status,
            "answer": safety.message,
            "refusal_code": safety.refusal_code,
            "retrieval": {"available": False, "method": "reviewed_lexical", "passages": []},
        })
    retrieval = farming_knowledge.retrieve_verified_knowledge(
        question, language=language, crop=_farmer_crop_hint()
    )
    if retrieval["available"]:
        return jsonify({
            "ok": True,
            "status": "OK",
            "answer": None,
            "answer_source": "retrieved_verified_knowledge",
            "retrieval": retrieval,
            "safety": {
                "status": safety.status,
                "refusal_code": safety.refusal_code,
                "message": safety.message,
            },
            "notice_key": "farmer.not_a_recommendation",
        })

    # Nothing verified matched. The honest state is stated in words the caller can
    # render as-is, so a client cannot end up showing a blank answer or improvising
    # one of its own.
    message_key = retrieval.get("reason_key") or "knowledge.no_results"
    return jsonify({
        "ok": True,
        "status": farming_knowledge.TOKEN_DATA_UNAVAILABLE,
        "answer": translate(message_key, language),
        "answer_source": "verified_knowledge_unavailable",
        "message_key": message_key,
        "hint": translate("knowledge.ask_unavailable_hint", language),
        "hint_key": "knowledge.ask_unavailable_hint",
        "retrieval": retrieval,
        "safety": {
            "status": safety.status,
            "refusal_code": safety.refusal_code,
            "message": safety.message,
        },
        "notice_key": "farmer.not_a_recommendation",
    })


__all__ = ["knowledge_bp"]
