"""Human-readable bilingual risk explanations (English + Odia).

Phase 1: all component lookups are defensive — components that are absent
(e.g. weather-driven ones when the provider is unavailable) simply do not
contribute reasons.
"""
from __future__ import annotations

from typing import Any, Mapping


def explain_reasons(
    crop: Mapping[str, Any],
    weather: Mapping[str, Any] | None,
    components: Mapping[str, float],
    leafscan: Mapping[str, Any],
    growth_stage: str,
    field_condition: str,
) -> dict[str, str]:
    """Explain the drivers behind a computed risk score."""
    reasons: list[str] = []
    odia: list[str] = []

    if components.get("Humidity", 0) >= 16:
        reasons.append("humidity is supporting fungal and sucking-pest activity")
        odia.append("ଅଧିକ ଆର୍ଦ୍ରତା ଫଙ୍ଗାଲ୍ ରୋଗ ଓ ରସ ଚୁଷୁଥିବା ପୋକକୁ ସହାୟତା କରିପାରେ")
    if components.get("Rainfall", 0) >= 12:
        reasons.append("recent rainfall or leaf wetness can increase disease spread")
        odia.append("ବର୍ଷା କିମ୍ବା ପତ୍ର ଭିଜା ରହିବାରୁ ରୋଗ ବଢ଼ିପାରେ")
    if components.get("Temperature", 0) >= 8:
        reasons.append("temperature is outside the crop's ideal comfort range")
        odia.append("ତାପମାତ୍ରା ଫସଲର ଉପଯୁକ୍ତ ସୀମାରୁ ବାହାରେ ରହିଛି")
    if components.get("Growth Stage", 0) >= 5:
        reasons.append(f"{growth_stage} stage is sensitive for yield and disease management")
        odia.append("ଏହି ବୃଦ୍ଧି ଅବସ୍ଥାରେ ଫସଲ ରୋଗ ଓ ଉତ୍ପାଦନ ପ୍ରତି ଅଧିକ ସମ୍ବେଦନଶୀଳ")
    if components.get("Field Condition", 0) >= 6:
        reasons.append(f"reported field condition indicates extra stress: {field_condition}")
        odia.append("ଖେତର ଦିଆଯାଇଥିବା ଅବସ୍ଥା ଅଧିକ ଚାପ ସୂଚାଉଛି")
    if leafscan.get("available") and components.get("Leaf Evidence", 0) >= 8:
        reasons.append("uploaded leaf image shows visible stress evidence")
        odia.append("ଅପଲୋଡ୍ କରାଯାଇଥିବା ପତ୍ର ଫଟୋରେ ଦୃଶ୍ୟମାନ ଚାପ ଲକ୍ଷଣ ମିଳିଛି")
    if weather is not None and not weather.get("available"):
        reasons.append("verified weather is currently unavailable, so weather-driven risk could not be evaluated")
    if not reasons:
        reasons.append("current conditions are not strongly favoring severe pest or disease pressure")
        odia.append("ବର୍ତ୍ତମାନ ପରିସ୍ଥିତି ଗୁରୁତର ରୋଗ କିମ୍ବା ପୋକ ଆକ୍ରମଣକୁ ଅଧିକ ସହାୟତା କରୁନାହିଁ")

    return {
        "en": "Risk is driven by " + "; ".join(reasons) + ".",
        "od": "ବିପଦର କାରଣ: " + "। ".join(odia) + "।",
    }


def odia_advisory(score: float) -> str:
    if score >= 80:
        return "ଫସଲରେ ବିପଦ ଅଧିକ ଅଛି। ଆଜି ଖେତ ଯାଞ୍ଚ କରନ୍ତୁ, ଆକ୍ରାନ୍ତ ଅଂଶ ହଟାନ୍ତୁ ଏବଂ ଆବଶ୍ୟକ ହେଲେ କୃଷି ବିଶେଷଜ୍ଞଙ୍କ ପରାମର୍ଶ ନିଅନ୍ତୁ।"
    if score >= 60:
        return "ଫସଲରେ ମଧ୍ୟମରୁ ଅଧିକ ବିପଦ ଦେଖାଯାଉଛି। ପତ୍ରର ତଳ ଭାଗ, ତଣ୍ଟି ଏବଂ ଭିଜା ସ୍ଥାନକୁ ଭଲଭାବେ ଯାଞ୍ଚ କରନ୍ତୁ।"
    if score >= 40:
        return "ବିପଦ ମଧ୍ୟମ ଅଛି। ଖେତକୁ ସଫା ରଖନ୍ତୁ, ଅଧିକ ନାଇଟ୍ରୋଜେନ୍ ଦିଅନ୍ତୁ ନାହିଁ ଏବଂ ନିୟମିତ ଦେଖନ୍ତୁ।"
    return "ବର୍ତ୍ତମାନ ବିପଦ କମ୍ ଅଛି। ସାଧାରଣ ଯତ୍ନ, ସଠିକ୍ ପାଣି ଏବଂ ସମତୁଳିତ ସାର ଜାରି ରଖନ୍ତୁ।"


def english_advisory(score: float, crop: Mapping[str, Any]) -> str:
    if score >= 80:
        return f"High urgency for {crop['name']}. Inspect today, remove infected parts, improve drainage and confirm before chemical treatment."
    if score >= 60:
        return f"{crop['name']} needs close monitoring within 24 hours. Start natural preventive care and track whether symptoms spread."
    if score >= 40:
        return f"{crop['name']} is in monitoring zone. Maintain field hygiene, avoid excess nitrogen and check after humidity or rain."
    return f"{crop['name']} looks comparatively safe now. Continue routine monitoring and balanced crop care."


__all__ = ["explain_reasons", "odia_advisory", "english_advisory"]
