"""Farmer action recommendations: plans, advisories, treatment console.

All content is transparent rule logic over the crop catalogue and risk
score. No pesticide dosage or legal prescription is ever produced; every
chemical mention requires confirmation and label compliance.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...core.constants import BASIS_RULE_HEURISTIC, TOKEN_HEURISTIC_NOT_VALIDATED
from ..catalogs.districts import profile_for
from .scoring import clamp, risk_status, yield_loss_band
from .scoring import urgency as urgency_label


def action_plan(score: float, crop: Mapping[str, Any], growth_stage: str, field_condition: str) -> list[str]:
    """7-day step-by-step plan scaled by risk band."""
    if score >= 80:
        return [
            "Today: inspect leaves, stem base, underside of leaves and wet patches.",
            "Today: isolate highly affected plant parts and avoid unnecessary movement through wet crop.",
            "Day 2: remove infected/damaged leaves or fruits and improve drainage/air movement.",
            "Day 3: apply natural preventive spray such as neem-based solution where suitable.",
            "Day 5: recheck pest count, leaf spots and new damage.",
            "Day 7: use chemical control only when severity is confirmed and local expert advice supports it.",
        ]
    if score >= 60:
        return [
            "Today: inspect the crop carefully, especially lower leaves and new growth.",
            "Day 2: remove damaged plant parts and keep the field clean.",
            "Day 3: use natural control and improve spacing/drainage where possible.",
            "Day 5: compare symptoms with today and look for spread.",
            "Day 7: escalate only if pest/disease pressure increases.",
        ]
    if score >= 40:
        return [
            "Today: monitor representative plants from different sides of the field.",
            "Day 3: keep the field weed-free and avoid excess nitrogen.",
            "Day 5: check underside of leaves and stem base again.",
            "Day 7: continue preventive natural care if weather stays humid.",
        ]
    return [
        "Today: continue normal monitoring.",
        "Day 3: maintain field hygiene and balanced irrigation.",
        "Day 5: check for early symptoms after rainfall or humid weather.",
        "Day 7: no urgent treatment needed unless new symptoms appear.",
    ]


def before_after(score: float) -> dict[str, Any]:
    """Before/after comparison shown on the impact card.

    Honest status (Phase 7 §2): the "after action" figure is an **illustrative
    scenario** (−18 points from the current heuristic score), not a forecast.
    AGRIQ holds no treatment-response data, so this cannot be presented as a
    predicted outcome — it carries ``status`` and ``basis`` and the UI labels it
    "illustrative, not a forecast".
    """
    reduced = int(clamp(score - 18, 15, 88))
    if score >= 70:
        potential = "High"
    elif score >= 45:
        potential = "Medium"
    else:
        potential = "Low to Medium"
    return {
        "untreated": yield_loss_band(score),
        "after_action_risk": f"{reduced}% • {risk_status(reduced)}",
        "protection": potential,
        "status": TOKEN_HEURISTIC_NOT_VALIDATED,
        "basis": BASIS_RULE_HEURISTIC,
        "message": "Early scouting and correct preventive action can reduce spread before yield loss becomes serious.",
    }


def digital_farm_twin(
    crop: Mapping[str, Any],
    district: str,
    weather: Mapping[str, Any],
    score: float,
    growth_stage: str,
    field_condition: str,
) -> dict[str, Any]:
    """Farm twin summary row set for the dashboard card."""
    profile = profile_for(district)
    likely = crop["diseases"].split(",")[0].strip()
    if score >= 60:
        problem = f"{likely} / {crop['pests'].split(',')[0].strip()} pressure"
    elif score >= 40:
        problem = "Early stress watch"
    else:
        problem = "Low current pressure"

    return {
        "district": district,
        "crop": crop["name"],
        "soil": profile["soil"],
        "zone": profile["zone"],
        "main": profile["main"],
        "stage": growth_stage,
        "field": field_condition,
        "weather": (
            f"{weather['temp']}°C • {weather['humidity']}% humidity • {weather['rain']} mm rain"
            if weather.get("temp") is not None
            else "Weather unavailable — verify field conditions directly"
        ),
        "likely": problem,
        "next_action": urgency_label(score),
    }


def build_treatment_console(
    crop: Mapping[str, Any],
    score: float,
    leafscan: Mapping[str, Any],
    field_condition: str,
    weather: Mapping[str, Any],
) -> dict[str, Any]:
    """Protection & Treatment console content (advisory, never prescription)."""
    likely_disease = crop["diseases"].split(",")[0].strip()
    likely_pest = crop["pests"].split(",")[0].strip()
    symptom = leafscan.get("symptom", "No image uploaded")

    fungal_pressure = any(
        word in likely_disease.lower()
        for word in ["blast", "blight", "rust", "mildew", "anthracnose", "spot", "rot", "sigatoka"]
    )
    insect_pressure = any(
        word in likely_pest.lower()
        for word in ["hopper", "borer", "whitefly", "aphid", "thrips", "mite", "fly", "weevil", "moth", "jassid"]
    )

    prevention = [
        f"Scout {crop['name']} in 5-10 representative spots before taking any treatment decision.",
        "Remove weeds and plant debris that can hold pests or disease spores.",
        "Improve spacing, air movement and drainage; avoid standing water around roots.",
        "Avoid excess nitrogen because soft growth can increase pest/disease pressure.",
    ]

    natural = [
        "Remove visibly infected leaves/fruits/shoots and keep them away from the field.",
        "Use neem-based spray or neem cake where suitable for early pest pressure.",
        "Use sticky traps or pheromone traps for flying/sucking/borer pests where locally available.",
        "Use compost, bio-control support such as Trichoderma/Pseudomonas only when suitable for the crop and local recommendation.",
        "Recheck symptoms after 48-72 hours and compare whether spread is increasing.",
    ]

    if "waterlogged" in field_condition.lower() or (weather.get("rain") or 0) > 8:
        natural.insert(1, "Open drainage channels and avoid field operations while the crop is wet.")
    if "leaf spot" in field_condition.lower() or "lesion" in symptom.lower() or fungal_pressure:
        natural.append(f"For suspected {likely_disease}, reduce leaf wetness and remove infected plant residue.")
    if insect_pressure:
        natural.append(f"For suspected {likely_pest}, check underside of leaves and new shoots before deciding treatment.")

    chemical = [
        f"Possible disease focus: {likely_disease}. If field symptoms confirm fungal/bacterial disease, use only a crop-registered and locally recommended fungicide/bactericide after expert confirmation.",
        f"Possible pest focus: {likely_pest}. If pest count crosses economic threshold, use only a crop-registered and locally recommended insecticide after local agriculture/KVK advice.",
        "Do not mix chemicals randomly. Do not repeat the same chemical group continuously because resistance may develop.",
        "Always follow the product label, waiting period, protective gear, wind/rain restrictions and local official advisory.",
    ]

    if score >= 70:
        decision_rule = "Risk is high: start natural/field sanitation immediately and escalate chemically only if symptoms are confirmed and spreading."
    elif score >= 45:
        decision_rule = "Risk is moderate: use prevention + natural care first; chemical step is not needed unless severity increases."
    else:
        decision_rule = "Risk is low: avoid unnecessary pesticide/fungicide use and continue monitoring."

    return {
        "possible_disease": likely_disease,
        "possible_pest": likely_pest,
        "symptom_basis": symptom,
        "prevention": prevention,
        "natural": natural,
        "chemical": chemical,
        "decision_rule": decision_rule,
        "disclaimer_en": "This console is advisory support only. It does not prescribe dosage or replace field diagnosis. Confirm symptoms, follow product label instructions, wear protective gear and consult a local agriculture officer/KVK/agronomist before any chemical use.",
        "disclaimer_od": "ଏହି କନସୋଲ୍ କେବଳ ପରାମର୍ଶ ପାଇଁ। ଏହା ଡୋଜ୍ ନିର୍ଦ୍ଦେଶ କରେ ନାହିଁ ଏବଂ ଖେତ ଯାଞ୍ଚର ପରିବର୍ତ୍ତନା ନୁହେଁ। ରାସାୟନିକ ବ୍ୟବହାର ପୂର୍ବରୁ ଲକ୍ଷଣ ନିଶ୍ଚିତ କରନ୍ତୁ, ଲେବଲ୍ ନିୟମ ମାନନ୍ତୁ ଏବଂ କୃଷି ଅଧିକାରୀ/KVK/ବିଶେଷଜ୍ଞଙ୍କ ପରାମର୍ଶ ନିଅନ୍ତୁ।",
    }


__all__ = ["action_plan", "before_after", "digital_farm_twin", "build_treatment_console"]
