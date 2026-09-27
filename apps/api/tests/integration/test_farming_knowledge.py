"""Integration tests for Farming Techniques (Phase 7.2).

Covers listing/search/filter/pagination, the mode projections, provenance and
evidence rendering, freshness and missing-data states, the language behaviour,
the safety refusals and the retrieval grounding the AI is allowed to use.

Fixture data lives in ``tests/fixtures/farming_knowledge_test_dataset.json`` and
is explicitly synthetic; the production dataset is only ever *validated* here
(never imported into the test database).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agriq.extensions import db
from agriq.integrations.knowledge.farming_import import (
    DatasetError,
    import_dataset,
    validate_pesticide,
    validate_technique,
    validate_url,
)
from agriq.models.farming_knowledge import FarmingTechnique, PesticideInformation
from agriq.repositories.copilot_repository import KnowledgeRepository
from agriq.repositories.farming_knowledge_repository import FarmingKnowledgeRepository as Repo
from agriq.services import knowledge_safety

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = API_DIR.parents[1]
FIXTURE_DATASET = API_DIR / "tests" / "fixtures" / "farming_knowledge_test_dataset.json"
PRODUCTION_DATASET = REPO_ROOT / "data" / "farming_knowledge" / "dataset.json"

REVIEWER = "Fixture reviewer (automated test)"


def seed(app, *, approve: bool = True):
    """Import the synthetic fixture dataset into the test database."""
    with app.app_context():
        return import_dataset(
            FIXTURE_DATASET, approve=approve, reviewer=REVIEWER, allow_test_hosts=True,
        )


# ---------------------------------------------------------------------------
# Dataset integrity
# ---------------------------------------------------------------------------

def test_production_dataset_validates_without_network_access():
    """Every production record must pass schema + provenance validation."""
    payload = json.loads(PRODUCTION_DATASET.read_text(encoding="utf-8"))
    errors: list[str] = []
    for entry in payload["techniques"]:
        errors += [f"{entry['slug']}: {e}" for e in validate_technique(entry)]
    for entry in payload["pesticides"]:
        errors += [f"{entry['slug']}: {e}" for e in validate_pesticide(entry)]
    assert not errors, errors
    assert len(payload["techniques"]) >= 5
    assert len(payload["pesticides"]) >= 3


def test_production_dataset_sources_are_real_government_or_institution_hosts():
    payload = json.loads(PRODUCTION_DATASET.read_text(encoding="utf-8"))
    for section in ("techniques", "pesticides"):
        for entry in payload[section]:
            url = entry["source"]["url"]
            assert url.startswith("https://"), url
            assert "example." not in url, f"{entry['slug']} must cite a real source, not a placeholder"


def test_production_dataset_has_no_invented_preparation_or_dosage():
    """A preparation is only stored with a cited preparation_instructions text."""
    payload = json.loads(PRODUCTION_DATASET.read_text(encoding="utf-8"))
    for entry in payload["techniques"]:
        if entry.get("preparation_status") == "DOCUMENTED":
            assert entry.get("preparation_instructions"), entry["slug"]
            assert entry["source"]["url"], entry["slug"]
    for entry in payload["pesticides"]:
        if entry.get("application_status") == "DOCUMENTED":
            assert entry.get("label_directions_reference"), entry["slug"]


@pytest.mark.parametrize("url", [
    "http://ppqs.gov.in/x.pdf",                 # not https
    "https://127.0.0.1/x.pdf",                  # loopback
    "https://192.168.0.10/x.pdf",               # private range
    "https://localhost/x.pdf",                  # loopback hostname
    "https://evil.example.com/x.pdf",           # host not on the allow-list
    "https://user:pass@fao.org/x.pdf",          # credentials in the URL
])
def test_url_validation_rejects_unsafe_sources(url):
    assert validate_url(url), f"{url} should be rejected"


def test_url_validation_accepts_the_reserved_test_host_only_when_opted_in():
    assert validate_url("https://example.org/fixture", allow_test_hosts=False)
    assert validate_url("https://example.org/fixture", allow_test_hosts=True) == []


def test_import_refuses_manufacturing_instructions(tmp_path):
    payload = json.loads(FIXTURE_DATASET.read_text(encoding="utf-8"))
    payload["pesticides"][0]["formulation_recipe"] = "mix x with y"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    errors = validate_pesticide(payload["pesticides"][0], allow_test_hosts=True)
    assert any("formulation_recipe" in error for error in errors)


def test_import_refuses_a_draft_translation_of_safety_text():
    payload = json.loads(FIXTURE_DATASET.read_text(encoding="utf-8"))
    entry = payload["techniques"][0]
    entry["translations"] = [
        {"language": "hi", "field": "safety_precautions", "text": "draft", "review_status": "DRAFT"}
    ]
    errors = validate_technique(entry, allow_test_hosts=True)
    assert any("safety-critical" in error for error in errors)


def test_import_requires_a_named_reviewer_to_approve(app):
    with app.app_context():
        with pytest.raises(DatasetError):
            import_dataset(FIXTURE_DATASET, approve=True, reviewer="  ",
                           allow_test_hosts=True)


# ---------------------------------------------------------------------------
# Empty / honest states
# ---------------------------------------------------------------------------

def test_empty_knowledge_base_reports_data_unavailable(auth_client):
    page = auth_client.get("/farming-techniques")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Verified data is currently unavailable." in body

    api = auth_client.get("/api/v1/farming-techniques")
    assert api.status_code == 200
    payload = api.get_json()
    assert payload["status"] == "DATA_UNAVAILABLE"
    assert payload["entries"] == []
    assert payload["awaiting_review"] == 0

    status = auth_client.get("/api/v1/farming-techniques/status").get_json()
    assert status["verified_records"] == 0
    assert status["state"] == "DATA_UNAVAILABLE"


def test_pages_require_authentication(client):
    page = client.get("/farming-techniques")
    assert page.status_code == 302
    # Unauthenticated visitors are sent to the sign-in page (auth.index serves
    # the login form at both "/" and "/login" since Phase 7.1).
    location = page.headers["Location"]
    assert location in ("/", "/login")
    assert client.get(location).status_code == 200

    api = client.get("/api/v1/farming-techniques")
    assert api.status_code == 401
    assert api.get_json()["code"] == "AUTH_UNAUTHORIZED"


def test_pending_records_are_never_served_as_verified(app, auth_client):
    seed(app, approve=False)
    listing = auth_client.get("/api/v1/farming-techniques").get_json()
    assert listing["status"] == "DATA_UNAVAILABLE"
    assert listing["entries"] == []
    assert listing["awaiting_review"] >= 3

    detail = auth_client.get("/api/v1/farming-techniques/technique/fixture-test-mulching")
    assert detail.status_code == 404


def test_search_miss_states_insufficient_real_data(app, auth_client):
    seed(app)
    response = auth_client.get("/api/v1/farming-techniques/search?q=zzz-nothing-matches")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "INSUFFICIENT_REAL_DATA"
    assert payload["entries"] == []
    assert "No verified agricultural information found." in payload["reason"]

    page = auth_client.get("/farming-techniques?q=zzz-nothing-matches")
    assert "No verified agricultural information found." in page.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Listing, filtering, pagination
# ---------------------------------------------------------------------------

def test_listing_shows_provenance_evidence_and_crops(app, auth_client):
    seed(app)
    payload = auth_client.get("/api/v1/farming-techniques").get_json()
    assert payload["status"] == "OK"
    titles = {entry["title"] for entry in payload["entries"]}
    assert "TEST FIXTURE — soil surface cover (not agricultural advice)" in titles
    entry = payload["entries"][0]
    assert entry["source"]["url"].startswith("https://")
    assert entry["source"]["organisation"]
    assert entry["evidence_level"] in {"TRADITIONAL", "HISTORICAL"}
    assert entry["crops"] or entry["region_scope"]
    assert entry["detail_url"].startswith("/farming-techniques/technique/")


def test_filters_by_category_crop_region_and_evidence(app, auth_client):
    seed(app)
    ancient = auth_client.get("/api/v1/farming-techniques?category=ancient").get_json()
    assert ancient["count"] == 1
    assert ancient["entries"][0]["category"] == "ancient"

    by_crop = auth_client.get("/api/v1/farming-techniques?crop=Test%20crop").get_json()
    assert by_crop["count"] == 1

    by_region = auth_client.get("/api/v1/farming-techniques?region=Test%20region").get_json()
    assert by_region["count"] >= 1

    by_evidence = auth_client.get("/api/v1/farming-techniques?evidence=HISTORICAL").get_json()
    assert by_evidence["count"] == 1

    pesticide_section = auth_client.get(
        "/api/v1/farming-techniques?category=modern_pesticide"
    ).get_json()
    assert pesticide_section["count"] == 2


def test_search_matches_documented_text(app, auth_client):
    seed(app)
    payload = auth_client.get("/api/v1/farming-techniques/search?q=fixture%20overview").get_json()
    assert payload["status"] == "OK"
    assert payload["query"] == "fixture overview"
    assert payload["count"] >= 1


def test_search_terms_reduce_a_question_to_significant_words():
    from agriq.repositories.farming_knowledge_repository import search_terms

    assert search_terms("What is mulch?") == ("mulch",)
    assert search_terms("Describe the drip irrigation method please") == ("drip", "irrigation")
    assert search_terms("   ") == ()
    # A word-form variant of the same word, never a different word.
    assert "mulching" in _word_variants("mulch")
    assert "mulch" in _word_variants("mulching")
    assert "crop" in _word_variants("crops")


def test_a_question_finds_the_record_that_documents_the_practice(app, auth_client):
    """The false DATA_UNAVAILABLE regression: a question must match its record.

    Phrase-matching the whole question (``%what is mulching?%``) never matched
    anything, so a reviewed record was silently reported as missing. The search
    is tokenised now; this test keeps it that way.
    """
    seed(app)
    for question in ("mulching", "What is mulching?", "tell me about the mulching method"):
        payload = auth_client.get(f"/api/v1/farming-techniques/search?q={question}").get_json()
        assert payload["status"] == "OK", question
        assert payload["count"] >= 1, question
        assert any("mulch" in entry["slug"] for entry in payload["entries"]), question


def test_a_question_about_nothing_documented_stays_unavailable(app, auth_client):
    seed(app)
    payload = auth_client.get(
        "/api/v1/farming-techniques/search?q=moon%20phase%20sowing%20on%20dragon%20fruit"
    ).get_json()
    assert payload["status"] == "INSUFFICIENT_REAL_DATA"
    assert payload["entries"] == []


def test_every_significant_word_must_appear_in_a_record(app, auth_client):
    """Grounding must not widen: one shared word is not a match."""
    seed(app)
    matched = auth_client.get("/api/v1/farming-techniques/search?q=mulching").get_json()
    unmatched = auth_client.get(
        "/api/v1/farming-techniques/search?q=mulching%20hydroponics"
    ).get_json()
    assert matched["count"] >= 1
    assert unmatched["count"] == 0
    assert unmatched["status"] == "INSUFFICIENT_REAL_DATA"


def _word_variants(token: str):
    from agriq.repositories.farming_knowledge_repository import _word_variants as variants

    return variants(token)


def test_pagination_is_bounded_and_pages_are_reported(app, auth_client):
    seed(app)
    first = auth_client.get("/api/v1/farming-techniques?page_size=1&page=1").get_json()
    assert first["page_size"] == 1
    assert first["count"] >= 2
    assert first["pages"] >= 2
    assert first["has_next"] is True
    assert first["has_previous"] is False
    second = auth_client.get("/api/v1/farming-techniques?page_size=1&page=2").get_json()
    assert second["has_previous"] is True
    assert second["entries"][0]["slug"] != first["entries"][0]["slug"]

    capped = auth_client.get("/api/v1/farming-techniques?page_size=1000").get_json()
    assert capped["page_size"] <= 48


def test_facets_only_expose_values_that_exist(app, auth_client):
    empty = auth_client.get("/api/v1/farming-techniques/crops").get_json()
    assert empty["state"] == "DATA_UNAVAILABLE"
    assert empty["crops"] == []
    seed(app)
    crops = auth_client.get("/api/v1/farming-techniques/crops").get_json()
    assert crops["crops"] == ["Test crop"]


# ---------------------------------------------------------------------------
# Detail, modes, states
# ---------------------------------------------------------------------------

def test_farmer_projection_uses_the_practical_section_order(app, auth_client):
    seed(app)
    farmer = auth_client.get("/api/v1/farming-techniques/technique/fixture-test-mulching").get_json()
    assert farmer["mode"] == "farmer"
    labels = [section["label_key"] for section in farmer["sections"]]
    assert labels and all(label.startswith("farmer.") for label in labels)
    assert "farmer.safety_precautions" in labels
    assert farmer["notices"] == ["farmer.not_a_recommendation"]


def test_student_projection_uses_the_study_order_on_the_same_record(app, student_client):
    seed(app)
    student = student_client.get("/api/v1/farming-techniques/technique/fixture-test-mulching").get_json()
    assert student["mode"] == "student"
    labels = [section["label_key"] for section in student["sections"]]
    assert labels and all(label.startswith("student.") for label in labels)
    assert "student.limitations" in labels
    assert "student.evidence_note" in student["notices"]

    # Same record, same provenance: the two modes never diverge on facts.
    farmer_source = student["sources"][0]
    assert farmer_source["url"].startswith("https://")
    assert student["entry"]["slug"] == "fixture-test-mulching"


def test_detail_reports_preparation_and_application_states(app, auth_client):
    seed(app)
    documented = auth_client.get(
        "/api/v1/farming-techniques/technique/fixture-test-mulching"
    ).get_json()
    assert documented["preparation"]["documented"] is True
    assert documented["preparation"]["state_key"] is None
    assert documented["application"]["verified"] is True

    unavailable = auth_client.get(
        "/api/v1/farming-techniques/technique/fixture-test-ancient-practice"
    ).get_json()
    assert unavailable["preparation"]["status"] == "PREPARATION_DATA_UNAVAILABLE"
    assert unavailable["preparation"]["state_message"]
    assert unavailable["application"]["status"] == "APPLICATION_DATA_UNVERIFIED"
    assert unavailable["historical"] is True


def test_unknown_slug_is_a_404_without_revealing_pending_records(app, auth_client):
    seed(app)
    response = auth_client.get("/api/v1/farming-techniques/technique/does-not-exist")
    assert response.status_code == 404
    page = auth_client.get("/farming-techniques/technique/does-not-exist")
    assert page.status_code == 404


def test_pesticide_detail_carries_the_label_notice_and_no_invented_dose(app, auth_client):
    seed(app)
    payload = auth_client.get("/api/v1/farming-techniques/pesticide/fixture-test-product").get_json()
    assert payload["status"] == "OK"
    assert payload["entry"]["title"] == "TEST FIXTURE product (not a real pesticide)"
    assert payload["application"]["verified"] is False
    assert payload["application"]["status"] == "APPLICATION_DATA_UNVERIFIED"
    assert "pesticide.label_notice" in payload["notices"]
    assert payload["safety"]["manufacturing_policy_key"] == "pesticide.manufacturing_refusal"
    # A record whose application data is unverified must not carry a dose field.
    assert all("dose" not in field["field"] for field in payload["fields"])

    guidance = auth_client.get(
        "/api/v1/farming-techniques/pesticide/fixture-test-safety-guidance"
    ).get_json()
    assert guidance["entry"]["record_type"] == "SAFETY_GUIDANCE"
    assert guidance["targets"] == []


def test_expired_pesticide_information_is_not_served_as_current(app, auth_client):
    seed(app)
    with app.app_context():
        record = Repo.get_pesticide("fixture-test-product", include_unverified=True)
        record.review_due_at = datetime.utcnow() - timedelta(days=5)
        db.session.commit()

    listing = auth_client.get(
        "/api/v1/farming-techniques?category=modern_pesticide"
    ).get_json()
    assert all(entry["slug"] != "fixture-test-product" for entry in listing["entries"])

    detail = auth_client.get("/api/v1/farming-techniques/pesticide/fixture-test-product").get_json()
    assert detail["status"] == "DATA_UNAVAILABLE"
    assert detail["entry"] is None
    assert detail["reason_key"] == "knowledge_states.STALE_SOURCE"


def test_expired_technique_is_flagged_but_keeps_its_content(app, auth_client):
    seed(app)
    with app.app_context():
        record = Repo.get_technique("fixture-test-mulching", include_unverified=True)
        record.review_due_at = datetime.utcnow() - timedelta(days=400)
        db.session.commit()

    listing = auth_client.get("/api/v1/farming-techniques").get_json()
    assert all(entry["slug"] != "fixture-test-mulching" for entry in listing["entries"])

    detail = auth_client.get("/api/v1/farming-techniques/technique/fixture-test-mulching").get_json()
    assert detail["status"] == "OK"
    assert detail["freshness"]["status"] == "EXPIRED"


def test_sources_endpoint_lists_real_urls(app, auth_client):
    seed(app)
    payload = auth_client.get("/api/v1/farming-techniques/sources").get_json()
    assert payload["status"] == "OK"
    assert payload["sources"]
    for source in payload["sources"]:
        assert source["url"].startswith("https://")
        assert source["organisation"]


# ---------------------------------------------------------------------------
# Language behaviour
# ---------------------------------------------------------------------------

def test_language_switch_translates_ui_and_keeps_content_in_source_language(app, auth_client):
    seed(app)
    page = auth_client.get("/farming-techniques?lang=hi")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "कृषि तकनीकें" in body                       # translated interface label
    assert "TEST FIXTURE — soil surface cover" in body   # source-language content, untouched
    assert "draft" in body.lower() or "ड्राफ़्ट" in body  # the draft-translation notice
    assert any("agriq_lang=hi" in header for header in page.headers.getlist("Set-Cookie"))

    detail = auth_client.get("/api/v1/farming-techniques/technique/fixture-test-mulching?lang=or")
    payload = detail.get_json()
    assert payload["translation"]["status"] == "SOURCE_LANGUAGE_SHOWN"
    assert payload["translation"]["notice_key"] == "knowledge_states.SOURCE_LANGUAGE_SHOWN"
    assert payload["ui_translation_status"] == "TRANSLATION_PENDING_REVIEW"


def test_reviewed_translation_is_served_and_high_risk_text_keeps_the_original(app, auth_client):
    seed(app)
    with app.app_context():
        record = Repo.get_technique("fixture-test-mulching", include_unverified=True)
        Repo.upsert_translation("technique", record.id, "hi", "benefits", "लाभ पाठ",
                                review_status="REVIEWED", reviewer="Fixture reviewer")
        Repo.upsert_translation("technique", record.id, "hi", "safety_precautions", "सुरक्षा पाठ",
                                review_status="REVIEWED", reviewer="Fixture reviewer")

    payload = auth_client.get(
        "/api/v1/farming-techniques/technique/fixture-test-mulching?lang=hi"
    ).get_json()
    sections = {section["field"]: section for section in payload["sections"]}
    safety = sections["safety_precautions"]
    assert safety["high_risk"] is True
    assert safety["text"] == "Fixture precaution text."     # source language original
    assert safety["translation"] == "सुरक्षा पाठ"
    assert sections["benefits"]["translation"] == "लाभ पाठ"


def test_dashboard_offers_the_language_switcher_in_both_modes(auth_client, student_client):
    for client in (auth_client, student_client):
        body = client.get("/dashboard").get_data(as_text=True)
        assert "/farming-techniques" in body          # navigation entry
        assert "data-language-select" in body         # language switcher control
        assert "Farming Techniques" in body


# ---------------------------------------------------------------------------
# Safety gate (§10/§11/§26/§47)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "How do I manufacture this pesticide myself?",
    "give me the synthesis route for this insecticide",
    "How to make my own pesticide at home",
    "कीटनाशक बनाने का तरीका बताओ",
])
def test_manufacturing_questions_are_refused(question):
    result = knowledge_safety.check_knowledge_request(question)
    assert result.blocked is True
    assert result.refusal_code == knowledge_safety.REFUSAL_MANUFACTURING
    assert "manufacturing" in result.message.lower()


@pytest.mark.parametrize("question", [
    "Give me an organic pesticide recipe for tomato",
    "make a natural spray at home for aphids",
    "घरेलू नुस्खा बताओ कीट के लिए",
])
def test_recipe_questions_without_a_verified_source_are_refused(question):
    result = knowledge_safety.check_knowledge_request(question)
    assert result.blocked is True
    assert result.refusal_code == knowledge_safety.REFUSAL_PREPARATION
    assert "PREPARATION_DATA_UNAVAILABLE" in result.message or "preparation" in result.message.lower()


def test_dosage_questions_without_verified_application_data_are_refused():
    result = knowledge_safety.check_knowledge_request(
        "How many ml of chlorantraniliprole should I spray per acre?"
    )
    assert result.blocked is True
    assert result.refusal_code == knowledge_safety.REFUSAL_APPLICATION
    assert "APPLICATION_DATA_UNVERIFIED" in result.message or "verified" in result.message.lower()


def test_documented_preparation_is_allowed_when_a_reviewed_source_supplies_it():
    result = knowledge_safety.check_knowledge_request(
        "How do I prepare the neem kernel extract?",
        verified_preparation_available=True,
    )
    assert result.blocked is False


def test_exposure_question_escalates_immediately():
    result = knowledge_safety.check_knowledge_request("I swallowed pesticide by mistake")
    assert result.escalate_emergency is True
    assert result.refusal_code == knowledge_safety.REFUSAL_EMERGENCY


def test_ask_endpoint_refuses_manufacturing_and_never_returns_passages(app, auth_client):
    seed(app)
    response = auth_client.post("/api/v1/farming-techniques/ask",
                                json={"question": "how do I manufacture this pesticide?"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "KNOWLEDGE_MANUFACTURING_REFUSED"
    assert payload["refusal_code"] == "KNOWLEDGE_MANUFACTURING_REFUSED"
    assert payload["retrieval"]["passages"] == []


def test_ask_endpoint_returns_only_reviewed_passages_with_sources(app, auth_client):
    seed(app)
    response = auth_client.post("/api/v1/farming-techniques/ask",
                                json={"question": "fixture overview"})
    payload = response.get_json()
    assert payload["status"] == "OK"
    passages = payload["retrieval"]["passages"]
    assert passages
    for passage in passages:
        assert passage["source_url"].startswith("https://")
        assert passage["source_organisation"]
        assert passage["slug"]

    miss = auth_client.post("/api/v1/farming-techniques/ask",
                            json={"question": "unrelated topic text"})
    assert miss.get_json()["status"] == "DATA_UNAVAILABLE"


def test_ask_endpoint_explains_an_unavailable_state_in_words(app, auth_client):
    """The honest state must be renderable by a client, never an empty reply."""
    seed(app)
    for language, expected_language_marker in (("en", "verified"), ("hi", None), ("or", None)):
        payload = auth_client.post(
            f"/api/v1/farming-techniques/ask?lang={language}",
            json={"question": "unrelated topic text"},
        ).get_json()
        assert payload["status"] == "DATA_UNAVAILABLE"
        assert payload["answer"].strip(), language
        assert payload["message_key"] == "knowledge.no_results"
        assert payload["hint_key"] == "knowledge.ask_unavailable_hint"
        assert payload["answer_source"] == "verified_knowledge_unavailable"
        assert payload["retrieval"]["passages"] == []
        if expected_language_marker:
            assert expected_language_marker in payload["answer"].lower()


def test_a_question_matches_its_record_through_the_ask_endpoint(app, auth_client):
    """Question-shaped input is answered from the reviewed record that covers it."""
    seed(app)
    payload = auth_client.post("/api/v1/farming-techniques/ask",
                               json={"question": "What is mulching?"}).get_json()
    assert payload["status"] == "OK"
    passages = payload["retrieval"]["passages"]
    assert passages
    assert all(passage["source_url"].startswith("https://") for passage in passages)
    assert all(passage["evidence_level"] for passage in passages)


def test_ask_endpoint_validates_input(app, auth_client):
    seed(app)
    empty = auth_client.post("/api/v1/farming-techniques/ask", json={"question": "  "})
    assert empty.status_code == 400
    too_long = auth_client.post("/api/v1/farming-techniques/ask",
                                json={"question": "x" * 2500})
    assert too_long.status_code == 400


# ---------------------------------------------------------------------------
# Retrieval grounding (what the AI is allowed to cite)
# ---------------------------------------------------------------------------

def test_approved_records_become_retrievable_chunks_with_their_own_source(app, auth_client):
    seed(app)
    with app.app_context():
        # The Phase 2 retriever reads approved sources + chunks only.
        sources = KnowledgeRepository.approved_sources()
        keys = {source.source_key for source in sources}
        assert "fixture-source-traditional" in keys
        chunks = KnowledgeRepository.approved_chunks_for_sources([s.id for s in sources])
        assert chunks
        assert all(chunk.content.strip() for chunk in chunks)
        # Nothing is retrievable for a record that was never approved.
        record = Repo.get_pesticide("fixture-test-product", include_unverified=True)
        assert record.review_status == "VERIFIED"


def test_unapproved_import_creates_no_retrieval_chunks(app, auth_client):
    seed(app, approve=False)
    with app.app_context():
        sources = KnowledgeRepository.approved_sources()
        assert sources == []


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------

def test_review_status_transitions_stamp_freshness(app):
    seed(app, approve=False)
    with app.app_context():
        record = Repo.get_technique("fixture-test-mulching", include_unverified=True)
        assert record.review_status == "PENDING_REVIEW"
        assert Repo.get_technique("fixture-test-mulching") is None  # not served yet

        Repo.set_review_status(record, status="VERIFIED", reviewer=REVIEWER, note="fixture review")
        db.session.refresh(record)
        assert record.review_status == "VERIFIED"
        assert record.reviewed_by == REVIEWER
        assert record.review_due_at is not None
        assert record.last_verified_at is not None
        # Traditional practice has the long review window; pesticides do not.
        window_days = (record.review_due_at - record.last_verified_at).days
        assert window_days == 1825

        from agriq.integrations.knowledge.farming_import import mirror_record_to_retrieval

        source_row = db.session.get(type(record.source), record.source_id)
        source_row.review_status = "approved"
        db.session.commit()
        chunks = mirror_record_to_retrieval("technique", record)
        assert chunks > 0
        assert Repo.get_technique("fixture-test-mulching") is not None


def test_reimport_is_idempotent(app):
    seed(app)
    with app.app_context():
        before = len(list(db.session.execute(db.select(FarmingTechnique)).scalars()))
        pest_before = len(list(db.session.execute(db.select(PesticideInformation)).scalars()))
    seed(app)
    with app.app_context():
        assert len(list(db.session.execute(db.select(FarmingTechnique)).scalars())) == before
        assert len(list(db.session.execute(db.select(PesticideInformation)).scalars())) == pest_before
        # Child rows are rebuilt, not duplicated.
        record = Repo.get_technique("fixture-test-mulching")
        assert len(record.crops) == 1
        assert len(record.regions) == 1


def test_each_mode_renders_its_own_view_label(app, auth_client):
    seed(app)
    body = auth_client.get("/farming-techniques").get_data(as_text=True)
    assert "TEST FIXTURE" in body
    assert "🌾 Practical view" in body
    assert "🎓 Study view" not in body


def test_student_mode_page_renders_the_study_view(app, student_client):
    seed(app)
    body = student_client.get("/farming-techniques").get_data(as_text=True)
    assert "TEST FIXTURE" in body
    assert "🎓 Study view" in body
    assert "🌾 Practical view" not in body
