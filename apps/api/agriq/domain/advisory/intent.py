"""Advisory intent categories with deterministic keyword routing.

Phase 2 supports the full farmer question space across Odia, Hindi and
English. Routing is deliberately rule-based (not LLM): intent detection must
be cheap, explainable and identical across users. When no category reaches
the keyword threshold the router returns ``general`` with a clarifying
question rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Intent constants
INTENT_FARM_ACTION = "farm_action"
INTENT_IRRIGATION = "irrigation"
INTENT_WEATHER = "weather_rainfall"
INTENT_SOWING = "sowing_preparation"
INTENT_TRANSPLANTING = "transplanting"
INTENT_STAGE_CARE = "crop_stage_care"
INTENT_NUTRIENT = "nutrient_symptom"
INTENT_PEST = "pest_symptom"
INTENT_DISEASE = "disease_symptom"
INTENT_WEED = "weed_management"
INTENT_HARVEST = "harvest_readiness"
INTENT_POST_HARVEST = "post_harvest"
INTENT_SOIL = "soil_information"
INTENT_MARKET = "market_price"
INTENT_CROP_CHOICE = "crop_choice"
INTENT_PREVIOUS_REC = "previous_recommendation"
INTENT_RECORD_OBSERVATION = "record_observation"
INTENT_EXPERT_HELP = "expert_help"
INTENT_GENERAL = "general_agriculture"

ALL_INTENTS = {
    INTENT_FARM_ACTION, INTENT_IRRIGATION, INTENT_WEATHER, INTENT_SOWING,
    INTENT_TRANSPLANTING, INTENT_STAGE_CARE, INTENT_NUTRIENT, INTENT_PEST,
    INTENT_DISEASE, INTENT_WEED, INTENT_HARVEST, INTENT_POST_HARVEST,
    INTENT_SOIL, INTENT_MARKET, INTENT_CROP_CHOICE, INTENT_PREVIOUS_REC,
    INTENT_RECORD_OBSERVATION, INTENT_EXPERT_HELP, INTENT_GENERAL,
}

# One short clarifying question per ambiguous pair / low confidence
CLARIFYING_QUESTIONS: dict[str, str] = {
    "en": "Could you tell me a bit more about what you need help with on your farm today?",
    "hi": "क्या आप थोड़ा और बता सकते हैं कि आज आपको अपने खेत में किस बात में मदद चाहिए?",
    "or": "ଆପଣ ଆଜି ନିଜ ପାଟିରେ କେଉଁ ବିଷୟରେ ସହାୟତା ଚାହୁଁଛନ୍ତି, ଦୟାକରି ଅଳ୍ପ ଅଧିକ କହନ୍ତୁ।",
}


@dataclass
class IntentResult:
    """Outcome of deterministic intent routing."""

    intent: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    clarifying_question: Optional[str] = None
    requires_tools: list[str] = field(default_factory=list)  # weather|market|knowledge|context

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < 0.5


def _count(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [kw for kw in keywords if kw in text]


# Keyword tables per intent. Odia is matched on raw script; Hindi on Devanagari
# plus common Latin transliterations so Romanised queries still route.
_INTENT_KEYWORDS: dict[str, tuple[tuple[str, ...], tuple[str, ...], float]] = {
    INTENT_IRRIGATION: (
        ("irrigate", "irrigation", "water the", "watering", "moisture"),
        ("पानी", "सिंचाई", "सिंचन", "pani", "sinchai", "paani"),
        ("ପାଣି", "ସେଚ", "ଜଳସେଚ", "ଡଙ୍କ"),
    ),
    INTENT_WEATHER: (
        ("weather", "rain", "rainfall", "forecast", "temperature", "humidity", "wind"),
        ("मौसम", "बारिश", "वर्षा", "तापमान", "mausam", "barish", "barsat"),
        ("ପାଣିପାଗ", "ବର୍ଷା", "ବର୍ଷଣ", "ତାପମାତ୍ରା", "ଧୂପ"),
    ),
    INTENT_SOWING: (
        ("sow", "sowing", "seed", "seeding", "plant seed", "nursery"),
        ("बोाई", "बुवाई", "बीज", "beej", "boai", "buvai"),
        ("ବୁଣିବା", "ବୁଣା", "ମାଞ୍ଜି", "ବିହନ"),
    ),
    INTENT_TRANSPLANTING: (
        ("transplant", "transplanting", "repot"),
        ("रोपाई", "रोपण", "ropaai", "ropan"),
        ("ରୋପଣ", "ପ୍ରତିରୋପଣ"),
    ),
    INTENT_STAGE_CARE: (
        ("stage", "growth", "tillering", "flowering", "booting", "panicle",
         "grain filling", "maturity", "vegetative"),
        ("अवस्था", "वृद्धि", "फूल", "avastha", "phool"),
        ("ଅବସ୍ଥା", "ବୃଦ୍ଧି", "ଫୁଲ", "ଫଳ"),
    ),
    INTENT_NUTRIENT: (
        ("yellow leaves", "yellowing", "turning yellow", "yellow leaf", "chlorosis", "nutrient",
         "deficiency", "fertiliser", "fertilizer", "urea", "nitrogen", "potash", "phosphorus", "dap"),
        ("पीला", "पोषक", "उर्वरक", "खाद", "नाइट्रोजन", "peela", "khad", "urea"),
        ("ହଳଦିଆ", "ପୋଷକ", "ସାର", "ପାତିଆ"),
    ),
    INTENT_PEST: (
        ("pest", "insect", "borer", "hopper", "aphid", "caterpillar", "bug", "worm"),
        ("कीट", "कीड़ा", "संक्रमण", "keet", "keeda", "kida"),
        ("ପୋକ", "ପୋକା", "କୀଟ"),
    ),
    INTENT_DISEASE: (
        ("disease", "blight", "rust", "rot", "spot", "mildew", "wilt", "fungus", "smut"),
        ("रोग", "बीमारी", "फंगस", "rog", "bimari"),
        ("ରୋଗ", "ବ୍ୟାଧି", "ଦାଗ", "ପଚା"),
    ),
    INTENT_WEED: (
        ("weed", "weeding", "herbicide", "grasses", "broadleaf"),
        ("खरपतवार", "गहाई", "kharpatwar", "gahai"),
        ("ଅଆଇସା", "ଘାସ", "ଆଇସାକଟା"),
    ),
    INTENT_HARVEST: (
        ("harvest", "cutting", "thresh", "when to cut", "maturity to harvest"),
        ("कटाई", "फसल काट", "mari", "katai"),
        ("ଅମଳ", "କଟାଣ", "ଫସଲ କାଟିବା"),
    ),
    INTENT_POST_HARVEST: (
        ("post harvest", "storage", "dry", "drying", "milling", "market after harvest"),
        ("भंडारण", "सुखाना", "sukhana", "bhandaran"),
        ("ସଂରକ୍ଷଣ", "ଶୁଖାଇବା", "ଗଦାନ"),
    ),
    INTENT_SOIL: (
        ("soil", "soil test", "ph", "organic carbon", "soil health"),
        ("मिट्टी", "माटी", "mitti", "mati"),
        ("ମାଟି", "ମାଟି ପରୀକ୍ଷା"),
    ),
    INTENT_MARKET: (
        ("market", "price", "mandi", "rate", "sell price", "modal price",
         # Phase 6 timing / routing vocabulary
         "sell now", "sell or wait", "should i sell", "where should i sell",
         "which mandi", "best price", "expected price", "price next week",
         "price forecast", "transport cost", "transport", "distance to market",
         "net value", "gross value"),
        ("मंडी", "भाव", "दाम", "मूल्य", "mandi", "bhav", "daam", "rate",
         "कहाँ बेच", "अगले हफ्ते भाव"),
        ("ମଣ୍ଡି", "ଦର", "ମୂଲ୍ୟ", "ବଜାର", "କେଉଁ ମଣ୍ଡି", "ବିକ୍ରି"),
    ),
    INTENT_CROP_CHOICE: (
        ("which crop", "what should i grow", "what to grow", "crop to grow",
         "grow this season", "which crop to plant", "crop choice",
         "crop recommendation", "best crop", "next crop", "plant instead"),
        ("कौन सी फसल", "कौनसी फसल", "क्या लगाएं", "क्या बोएं", "kaunsi fasal", "kya lagaye"),
        ("କେଉଁ ଫସଲ", "କଣ ଲଗାଇବି", "କେଉଁ ଫସଲ ଲଗାଇବି"),
    ),
    INTENT_PREVIOUS_REC: (
        ("previous recommendation", "last advice", "earlier suggestion", "my recommendation"),
        ("पिछली सलाह", "pichli salah"),
        ("ପୂର୍ବ ସୁପାରିଶ",),
    ),
    INTENT_RECORD_OBSERVATION: (
        ("record observation", "note in my log", "save observation", "log that"),
        ("अवलोकन दर्ज", "avalokan darj"),
        ("ପର୍ଯ୍ୟବେକ୍ଷଣ ଲେଖ",),
    ),
    INTENT_EXPERT_HELP: (
        ("expert", "agriculture officer", "kvk", "agronomist", "scientist", "help me contact"),
        ("विशेषज्ञ", "कृषि अधिकारी", "vishesagya", "krishi adhikari"),
        ("ବିଶେଷଜ୍ଞ", "କୃଷି ଅଧିକାରୀ", "ବୈଜ୍ଞାନିକ"),
    ),
    INTENT_FARM_ACTION: (
        ("today", "what should i do", "what to do now", "this week", "action"),
        ("आज", "अभी क्या", "aaj", "abhi kya"),
        ("ଆଜି", "ଏବେ କଣ", "କଣ କରିବି"),
    ),
}

# Simple linguistic noise tokens skipped in scoring
_STOPWORDS = {"the", "a", "an", "is", "my", "i", "to", "for", "and", "of", "in", "on"}


def route_intent(text: str) -> IntentResult:
    """Deterministically classify a farmer question.

    The score is ``matched / keywords_present_budget`` where matching against
    longer, more specific phrases weighs more. Ties resolve by a fixed intent
    order so behaviour is reproducible.
    """
    lowered = (text or "").lower().strip()
    if not lowered:
        return IntentResult(intent=INTENT_GENERAL, confidence=0.0,
                            clarifying_question=CLARIFYING_QUESTIONS["en"])

    best_intent: str = INTENT_GENERAL
    best_score: float = 0.0
    best_keywords: list[str] = []

    for intent in _INTENT_KEYWORDS:
        en_kw, hi_kw, or_kw = _INTENT_KEYWORDS[intent]
        matched = _count(lowered, en_kw) + _count(lowered, hi_kw) + _count(lowered, or_kw)
        # Weight: each distinct match counts; cap so one intent with many weak
        # matches cannot dominate a single strong phrase match.
        if not matched:
            continue
        specific = [kw for kw in matched if " " in kw]
        score = min(1.0, 0.34 * len(matched) + 0.16 * len(specific))
        if score > best_score:
            best_intent, best_score, best_keywords = intent, score, matched

    # Fertiliser/nutrient and disease/pest share vocabulary; keep the more
    # specific family when both hit equally.
    if best_score < 0.5:
        tools = _default_tools(best_intent)
        return IntentResult(
            intent=best_intent,
            confidence=best_score,
            matched_keywords=best_keywords,
            clarifying_question=CLARIFYING_QUESTIONS.get("en"),
            requires_tools=tools,
        )
    return IntentResult(intent=best_intent, confidence=best_score,
                        matched_keywords=best_keywords,
                        requires_tools=_default_tools(best_intent))


def _default_tools(intent: str) -> list[str]:
    """Which internal tools the orchestrator should invoke for an intent."""
    tools = ["context", "knowledge"]
    if intent in (INTENT_IRRIGATION, INTENT_FARM_ACTION, INTENT_WEATHER,
                  INTENT_STAGE_CARE, INTENT_SOWING, INTENT_TRANSPLANTING,
                  INTENT_HARVEST):
        tools.append("weather")
    if intent == INTENT_MARKET:
        tools.append("market")
    # Crop choice reads stored official price history but never triggers one
    # provider call per candidate crop, so it needs no "market" tool.
    return tools


__all__ = [
    "route_intent", "IntentResult", "CLARIFYING_QUESTIONS", "ALL_INTENTS",
    "INTENT_FARM_ACTION", "INTENT_IRRIGATION", "INTENT_WEATHER", "INTENT_SOWING",
    "INTENT_TRANSPLANTING", "INTENT_STAGE_CARE", "INTENT_NUTRIENT", "INTENT_PEST",
    "INTENT_DISEASE", "INTENT_WEED", "INTENT_HARVEST", "INTENT_POST_HARVEST",
    "INTENT_SOIL", "INTENT_MARKET", "INTENT_CROP_CHOICE", "INTENT_PREVIOUS_REC",
    "INTENT_RECORD_OBSERVATION", "INTENT_EXPERT_HELP", "INTENT_GENERAL",
]
