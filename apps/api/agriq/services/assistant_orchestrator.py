"""Assistant orchestrator (ARC-06/AI-01 groundwork).

Order of answer resolution:
1. Gemini (only when ``GEMINI_API_KEY`` is configured).
2. Transparent built-in knowledge engine (farmer or student mode).

A scripted knowledge-engine answer is always our own curated engine output;
a Gemini failure produces a clear unavailable state, never a substituted
answer presented as Gemini.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..core.config import BaseConfig
from ..core.logging import get_logger
from ..core.text import has_any
from ..domain.catalogs.crops import resolve_crop
from ..domain.catalogs.diseases import DISEASE_LIBRARY
from ..domain.catalogs.education import ANIMAL_LIBRARY, PEST_LIBRARY, STUDENT_AREAS
from ..domain.catalogs.soils import SOIL_LIBRARY
from ..integrations.ai import gemini
from .student_intelligence import (
    build_calculator_guides,
    build_career_guidance,
    build_question_bank,
    build_research_methodology_guides,
    build_student_research_plan,
    library_lookup,
    make_viva_questions,
)

logger = get_logger("services.assistant")

ASSISTANT_UNAVAILABLE_MESSAGE = (
    "The AI assistant is not available right now, so no generated answer is shown. "
    "Verified AGRIQ guidance from your farm data still works on the dashboard."
)

ASSISTANT_NOT_CONFIGURED_MESSAGE = (
    "The AI assistant is not configured on this deployment, so no generated answer is shown. "
    "Verified AGRIQ guidance from your farm data still works on the dashboard."
)


def generate_student_ai_answer(question: str, context: Mapping[str, Any] | None = None) -> str:
    """Deterministic student-mode answer engine (curriculum-style)."""
    context = context or {}
    q = (question or "").strip()
    q_lower = q.lower()
    area = context.get("learning_area") or "Agronomy"
    if area not in STUDENT_AREAS:
        area = "Agronomy"
    topic = context.get("topic") or STUDENT_AREAS.get(area, ["Agriculture"])[0]
    crop_name = context.get("crop") or "Rice"
    crop, _ = resolve_crop(crop_name)
    pest_name, pest = library_lookup(PEST_LIBRARY, context.get("pest_focus"), "Brown Plant Hopper")
    disease_name, disease = library_lookup(DISEASE_LIBRARY, context.get("disease_focus"), "Blast")
    soil_type, soil = library_lookup(SOIL_LIBRARY, context.get("soil_type"), "Alluvial soil")
    animal_species, animal = library_lookup(ANIMAL_LIBRARY, context.get("animal_species"), "Dairy cattle")
    academic_level = context.get("academic_level", "B.Sc Agriculture Semester 3-4")
    purpose = context.get("study_purpose", "Exam Preparation")
    district = context.get("district", "Cuttack")

    bank = build_question_bank(area, topic, crop, pest_name, disease_name, academic_level)
    guide = build_research_methodology_guides(area, topic, crop, district)
    research = build_student_research_plan(area, topic, crop, pest_name, disease_name, animal_species, district, academic_level)

    intro = (
        f"AGRIQ Student Answer\n"
        f"Topic: {topic}\nDomain: {area}\nLevel: {academic_level}\n"
        f"Focus: {animal_species if area == 'Animal Husbandry & Fisheries' else crop['name']}\n"
    )

    if has_any(q_lower, ["mcq", "objective", "quiz"]):
        lines = [intro, "MCQ practice with 4 options:"]
        for i, m in enumerate(bank["mcqs"], 1):
            lines.append(f"\n{i}. {m['q']}")
            for opt in m.get("option_rows", []):
                lines.append(f"   {opt['label']}. {opt['text']}")
            lines.append(f"   Answer: {m['answer']}")
            lines.append(f"   Explanation: {m['explain']}")
        return "\n".join(lines)

    if has_any(q_lower, ["assignment", "important question", "question bank", "questions"]):
        return (
            intro + "\nImportant questions:\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(bank["important"]))
            + "\n\nAssignment questions:\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(bank["assignment"]))
        )

    if has_any(q_lower, ["viva", "oral", "interview"]):
        questions = make_viva_questions(area, topic, crop, pest_name, disease_name, animal_species)
        return intro + "\nViva preparation:\n" + "\n".join(
            f"{i+1}. {x}\n   Answer style: one-line definition + field example + one management point."
            for i, x in enumerate(questions)
        )

    if has_any(q_lower, ["research methodology", "methodology", "proposal", "thesis", "research", "project"]):
        return (
            intro
            + f"\nResearch title: {research['title']}\n"
            + "Objectives:\n" + "\n".join(f"• {x}" for x in research["objectives"])
            + "\n\nHypothesis:\n• " + research["hypothesis"]
            + "\n\nVariables:\n" + "\n".join(f"• {x}" for x in research["variables"])
            + "\n\nMethodology steps:\n" + "\n".join(f"• {x}" for x in guide["methodology_steps"])
            + "\n\nStatistical analysis:\n" + "\n".join(f"• {x}" for x in guide["statistical_analysis"])
            + "\n\nReport format:\n" + " → ".join(guide.get("report_format", []))
        )

    if has_any(q_lower, ["statistics", "statistical", "anova", "correlation", "regression", "t-test", "chi-square"]):
        return (
            intro + "\nStatistical analysis guide:\n" + "\n".join(f"• {x}" for x in guide["statistical_analysis"])
            + "\n\nUse simple tables and graphs first. Do not apply advanced tests without suitable sample size and clean data."
        )

    if has_any(q_lower, ["plagiarism", "citation", "reference", "bibliography", "copy"]):
        return intro + "\nPlagiarism-safe writing guide:\n" + "\n".join(f"• {x}" for x in guide["plagiarism_guidance"])

    if has_any(q_lower, ["career", "exam", "job", "future", "icar", "jrf", "afo", "nabard"]):
        career = build_career_guidance(area, academic_level)
        return (
            intro + "\nCareer direction: " + career["focus"] + "\n"
            + "\n".join(f"• {p['path']}\n  Exams/routes: {p['exams']}\n  Preparation: {p['prep']}" for p in career["paths"])
            + "\n" + career["disclaimer"]
        )

    if has_any(q_lower, ["fertilizer", "seed rate", "calculator", "unit", "urea", "dap", "mop"]):
        calc = build_calculator_guides(crop)
        return (
            intro
            + "\nCalculator and input guidance:\n"
            + f"• Fertilizer dose formula: {calc['fertilizer']['formula']} Example: {calc['fertilizer']['example']}\n"
            + f"• Seed rate formula: {calc['seed_rate']['formula']} Example: {calc['seed_rate']['example']}\n"
            + f"• Unit converter: {calc['unit_converter']['area']}; {calc['unit_converter']['weight']}; {calc['unit_converter']['water']}\n"
            + "• Exact field fertilizer dose must be based on soil test, crop stage and local package of practices."
        )

    if has_any(q_lower, ["pest", "insect", "life cycle", "ipm"]):
        return (
            intro
            + f"\nPest study card: {pest_name}\n"
            + f"• Type: {pest['type']}\n• Hosts: {pest['hosts']}\n• Identification: {pest['id']}\n"
            + f"• Damage: {pest['damage']}\n• Life cycle: {pest['life']}\n• IPM: {pest['management']}\n"
            + "Exam format: identification → damage → life cycle → ETL/scouting → IPM."
        )

    if has_any(q_lower, ["disease", "symptom", "pathology", "idm", "blast", "blight", "wilt", "rust"]):
        return (
            intro
            + f"\nDisease study card: {disease_name}\n"
            + f"• Agent: {disease['agent']}\n• Hosts: {disease['hosts']}\n• Symptoms: {disease['symptom']}\n"
            + f"• Favourable condition: {disease['favour']}\n• Disease cycle: {disease['cycle']}\n• IDM: {disease['management']}\n"
            + "Answer format: definition → causal organism → symptom → favourable condition → disease cycle → management."
        )

    if has_any(q_lower, ["soil", "water", "irrigation", "ph", "ec", "salinity"]):
        return (
            intro
            + f"\nSoil and water answer:\n• Selected soil: {soil_type}\n• Features: {soil['features']}\n"
            + f"• Problems: {soil['problems']}\n• Management: {soil['management']}\n"
            + "• Irrigation choice depends on soil texture, crop stage, slope, water availability and disease risk. Avoid waterlogging and confirm exact recommendation with local advisory."
        )

    if area == "Animal Husbandry & Fisheries" or has_any(q_lower, ["dairy", "goat", "poultry", "fish", "animal"]):
        return (
            intro
            + f"\n{animal_species} answer:\n• Focus: {animal['focus']}\n• Records: {animal['records']}\n"
            + f"• Exam point: {animal['exam']}\n• Research idea: {animal['research']}\n"
            + "Research approach: record management factor, production output, health events and cost-benefit data."
        )

    return (
        intro
        + f"\nDetailed agriculture answer for: {q or topic}\n"
        + f"1. Meaning: {topic} is connected with crop production, soil, water, pest/disease pressure, climate and management decisions.\n"
        + f"2. Field example: In {crop['name']}, connect this topic with season ({crop['season']}), suitable soil ({crop['soil']}), pests ({crop['pests']}) and diseases ({crop['diseases']}).\n"
        + "3. Practical explanation: Observe crop stage, symptom, affected plant %, soil moisture, weather and farmer practice before concluding.\n"
        + "4. Exam answer structure: definition → importance → field example → management → limitation.\n"
        + "5. Research structure: title → objectives → variables → sampling → data table → statistics → conclusion.\n"
        + "6. Safety: Do not give exact chemical/fertilizer dose without soil test, label and local official recommendation."
    )


def generate_farmer_ai_answer(question: str, context: Mapping[str, Any] | None = None) -> str:
    """Deterministic farmer-mode answer engine (curated field guidance).

    Retained for the knowledge engine surface and Student-adjacent flows;
    farmer-mode assistant requests no longer silently use it as an AI
    substitute (see :func:`ask`).
    """
    from ..integrations.weather import open_meteo

    context = context or {}
    q = (question or "").strip()
    q_lower = q.lower()
    crop_name = context.get("crop") or "Rice"
    district = context.get("district") or "Cuttack"
    stage = context.get("growth_stage") or "Vegetative"
    condition = context.get("field_condition") or "Normal field"
    crop, _ = resolve_crop(crop_name)
    weather = open_meteo.get_weather(district)
    likely_pest = crop["pests"].split(",")[0].strip()
    likely_disease = crop["diseases"].split(",")[0].strip()

    header = (
        f"AGRIQ Farmer Answer\nCrop: {crop['name']}\nDistrict: {district}\nStage: {stage}\n"
        f"Field condition: {condition}\n"
        f"Weather: {weather.get('temp')}°C, {weather.get('humidity')}% humidity, {weather.get('rain')} mm rain\n"
    )

    if has_any(q_lower, ["today", "what should", "action", "do now", "urgent", "next step"]):
        return (
            header + "\nToday’s action plan:\n• Scout 5-10 spots in the field, not only one corner.\n"
            "• Check leaf underside, stem base, tender shoots, flowers/fruits and waterlogged patches.\n"
            f"• Look especially for {likely_pest} and {likely_disease} symptoms.\n"
            "• Remove infected/damaged parts where practical and improve drainage/air movement.\n"
            "• Use natural/preventive steps first. Use chemical only after confirmed pest/disease and local expert advice."
        )

    if has_any(q_lower, ["pest", "insect", "bug", "worm", "borer", "hopper", "aphid", "whitefly"]):
        return (
            header + f"\nLikely pest focus: {likely_pest}\n"
            "• Identification: check underside of leaves, tender shoots, stem/fruit holes, sticky honeydew or hopper movement depending on pest.\n"
            "• Damage check: count affected plants and compare with healthy plants.\n"
            "• First response: field sanitation, traps where suitable, avoid excess nitrogen and monitor for 48-72 hours.\n"
            "• Escalation: use crop-registered pesticide only if pest crosses threshold and after local advisory."
        )

    if has_any(q_lower, ["disease", "symptom", "spot", "blight", "blast", "wilt", "yellow", "curl", "rot"]):
        return (
            header + f"\nLikely disease focus: {likely_disease}\n"
            "• Check symptoms: spots/lesions, yellowing, wilting, rotting, curling or abnormal growth.\n"
            "• Risk reason: high humidity, rain/leaf wetness, dense canopy and waterlogging can increase disease spread.\n"
            "• First response: remove infected plant parts, improve drainage, avoid overhead irrigation and avoid working when plants are wet.\n"
            "• Confirm diagnosis before any chemical step."
        )

    if has_any(q_lower, ["fertilizer", "urea", "dap", "mop", "npk", "nutrient", "deficiency"]):
        return (
            header + f"\nFertilizer guidance for {crop['name']}:\n"
            "• Do not guess exact dose from the app alone. Soil test and local package of practices are needed.\n"
            "• Avoid excess nitrogen because it can make soft growth and increase pest/disease pressure.\n"
            "• Split fertilizer where recommended, keep field moisture suitable and avoid application before heavy rain.\n"
            "• If deficiency is visible, record leaf colour, old/new leaf location and pattern, then confirm with soil/leaf test or local officer."
        )

    if has_any(q_lower, ["irrigation", "water", "waterlogging", "rain", "dry", "drought"]):
        return (
            header + "\nWater/irrigation guidance:\n"
            "• If waterlogged: open drainage channels and avoid field operations until excess water reduces.\n"
            "• If dry stress: irrigate based on crop stage, soil type and available water. Flowering/fruiting stages are usually more sensitive.\n"
            "• Avoid wetting leaves repeatedly in disease-prone weather.\n"
            "• For drip/sprinkler/canal choice, consider crop, soil texture, slope, water availability and cost."
        )

    if has_any(q_lower, ["weather", "spray", "wind", "humidity", "forecast"]):
        return (
            header + "\nWeather-based decision:\n"
            "• High humidity/leaf wetness can increase fungal and bacterial disease risk.\n"
            "• Avoid spraying during strong wind, rain, very hot hours or when rain is expected soon.\n"
            "• Prefer calm, dry windows and follow label safety instructions.\n"
            "• Weather data is advisory; field observation is still necessary."
        )

    if has_any(q_lower, ["natural", "organic", "neem", "bio", "low cost"]):
        return (
            header + "\nNatural/low-cost plan:\n"
            "• Remove infected/damaged leaves, fruits and shoots.\n"
            "• Maintain drainage, spacing and field sanitation.\n"
            "• Use sticky/pheromone traps where suitable for the pest.\n"
            "• Neem-based support may help in early sucking pest pressure where locally recommended.\n"
            "• Use compost/bio-control support only when suitable for crop and local recommendation."
        )

    if has_any(q_lower, ["chemical", "pesticide", "fungicide", "insecticide", "spray", "dose"]):
        return (
            header + "\nChemical safety answer:\n"
            "• Chemical is the last step, not the first step.\n"
            "• Confirm pest/disease and severity first.\n"
            "• Use only crop-registered and locally recommended product.\n"
            "• Follow label dose, waiting period, protective gear and wind/rain restrictions.\n"
            "• Do not mix chemicals randomly and do not repeat the same chemical group continuously."
        )

    if has_any(q_lower, ["yield", "profit", "market", "loss", "productivity"]):
        return (
            header + f"\nYield/profit protection:\n"
            f"• In {stage} stage, protect plant stand, root health, leaves and reproductive parts.\n"
            "• Early scouting prevents spread before yield loss becomes serious.\n"
            "• Keep records of input cost, symptom date, affected area and action taken.\n"
            "• Market decision should consider harvest stage, quality, local price and storage capacity."
        )

    if has_any(q_lower, ["odia", "ଓଡ଼ିଆ"]):
        return (
            header + "\nଓଡ଼ିଆ ପରାମର୍ଶ:\n"
            "• ଖେତର ୫-୧୦ଟି ସ୍ଥାନ ଯାଞ୍ଚ କରନ୍ତୁ।\n"
            "• ପତ୍ର ତଳ, କାଣ୍ଡ, ଫଳ/ଫୁଲ ଓ ପାଣି ଜମା ଅଞ୍ଚଳ ଦେଖନ୍ତୁ।\n"
            "• ପ୍ରଥମେ ନିଷ୍କାଶନ, ସଫାସୁଫାଇ ଓ ପ୍ରାକୃତିକ ପଦକ୍ଷେପ ନିଅନ୍ତୁ।\n"
            "• ରାସାୟନିକ ବ୍ୟବହାର ପୂର୍ବରୁ କୃଷି ଅଧିକାରୀ/KVK ପରାମର୍ଶ ନିଅନ୍ତୁ।"
        )

    return (
        header
        + f"\nI can answer agriculture questions about {crop['name']} crop production, pest/disease diagnosis, fertilizer, irrigation, natural solution, chemical safety, weather risk, yield, market and farmer advisory.\n"
        + f"For your question: {q or 'general farming'}, use this structure: observe symptoms → connect with crop stage and weather → take prevention/natural action → confirm before chemical/fertilizer dose → monitor result after 2-3 days."
    )


def ask(question: str, mode: str, context: Mapping[str, Any] | None, config: BaseConfig) -> dict[str, Any]:
    """Resolve an assistant question and return a structured response.

    Returns ``{"answer": str, "source": "gemini" | "knowledge_engine" | "unavailable",
    "ok": bool}``.

    Phase 1 real-data policy: when Gemini is not configured or fails, the
    orchestrator returns an explicit unavailable state — the scripted
    engines are our own curated reference content and are ONLY used for the
    Student/Research workspace, where they are always labelled as the AGRIQ
    knowledge engine (never as AI/Gemini output).
    """
    question = (question or "").strip()
    context = dict(context or {})

    gemini_answer = gemini.generate_answer(
        question=question,
        mode=mode,
        context=context,
        api_key=config.get("GEMINI_API_KEY", ""),
        model=config.get("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    if gemini_answer:
        return {"answer": gemini_answer, "source": "gemini", "ok": True}

    if mode == "student":
        answer = generate_student_ai_answer(question, context)
        return {"answer": answer, "source": "knowledge_engine", "ok": True,
                "source_label": "AGRIQ knowledge engine (rule-based reference)"}

    # Farmer mode without Gemini: explicit unavailable state.
    return {
        "answer": ASSISTANT_UNAVAILABLE_MESSAGE,
        "source": "unavailable",
        "ok": False,
        "reason": "gemini_not_configured" if not gemini.is_configured(config.get("GEMINI_API_KEY", "")) else "gemini_failed",
    }


__all__ = [
    "ask",
    "generate_farmer_ai_answer",
    "generate_student_ai_answer",
    "ASSISTANT_UNAVAILABLE_MESSAGE",
    "ASSISTANT_NOT_CONFIGURED_MESSAGE",
]
