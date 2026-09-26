"""Crop knowledge base: crop profiles, aliases and market baseline bands."""
from __future__ import annotations

from typing import Any

# REMOVED in Phase 7 (§53 hardcoded-value audit): a hand-curated
# ``MARKET_BASELINE`` table of ₹/quintal bands for 26 crops used to live here.
# It recorded no source, citation, retrieval date, licence or update
# frequency, it was rendered to farmers as a rupee price range, and it applied
# an invented fallback band to any crop missing from the table. Under the
# real-data policy ("every production numerical value must have a legitimate
# source") it could not be labelled honestly, so it was deleted rather than
# relabelled. Rupee values now come ONLY from the AGMARKNET provider through
# ``services/market_service`` / ``services/market_intelligence``, and are
# reported unavailable when that provider cannot be reached.

GROWTH_STAGES: list[str] = [
    "Seedling",
    "Vegetative",
    "Flowering",
    "Fruiting / Grain Filling",
    "Harvest Stage",
]

FIELD_CONDITIONS: list[str] = [
    "Normal field",
    "Humid field",
    "Waterlogged field",
    "Dry stress field",
    "Visible pest symptoms",
    "Visible leaf spots",
]


def crop_item(
    name: str,
    odia: str,
    category: str,
    scientific: str,
    season: str,
    soil: str,
    pests: str,
    diseases: str,
    sensitivity: int,
    ideal_temp: tuple[int, int],
    humidity_risk: int,
    rainfall_risk: int,
    management: str,
) -> dict[str, Any]:
    """Build a crop knowledge record with a stable key set."""
    return {
        "name": name,
        "odia": odia,
        "category": category,
        "scientific": scientific,
        "season": season,
        "soil": soil,
        "pests": pests,
        "diseases": diseases,
        "sensitivity": sensitivity,
        "ideal_temp": ideal_temp,
        "humidity_risk": humidity_risk,
        "rainfall_risk": rainfall_risk,
        "management": management,
    }


def _general_crop(display_name: str) -> dict[str, Any]:
    """Fallback crop profile for unknown crop names (transparent, curated)."""
    return crop_item(
        display_name,
        "ଫସଲ",
        "General",
        "Crop profile",
        "Season depends on variety",
        "Well-drained fertile soil",
        "Sucking pests, caterpillars, borers",
        "Leaf spot, blight, wilt, fungal disease",
        6,
        (22, 34),
        76,
        8,
        "Use clean seed, correct spacing, balanced fertilizer, crop rotation and regular field scouting.",
    )


CROPS: dict[str, Any] = {
    "rice": crop_item("Rice", "ଧାନ", "Cereal", "Oryza sativa", "Kharif", "Clay loam / alluvial", "Brown Plant Hopper, Stem Borer, Leaf Folder", "Blast, Bacterial Leaf Blight, Sheath Blight", 9, (24, 34), 78, 12, "Maintain drainage, monitor lower leaves, avoid excess nitrogen and scout after humid/rainy periods."),
    "paddy": "rice",
    "wheat": crop_item("Wheat", "ଗହମ", "Cereal", "Triticum aestivum", "Rabi", "Loam soil", "Aphids, Termites", "Rust, Smut", 6, (18, 28), 75, 8, "Avoid late irrigation, scout for rust, use balanced nitrogen and timely sowing."),
    "maize": crop_item("Maize", "ମକା", "Cereal", "Zea mays", "Kharif / Rabi", "Well-drained fertile loam", "Fall Armyworm, Stem Borer", "Leaf Blight, Rust", 7, (21, 32), 76, 10, "Check whorl damage, keep field clean and use pheromone traps for armyworm monitoring."),
    "ragi": crop_item("Ragi", "ମାଣ୍ଡିଆ", "Millet", "Eleusine coracana", "Kharif", "Red loam / light soil", "Shoot Fly, Aphids", "Blast, Leaf Spot", 5, (22, 34), 82, 15, "Maintain spacing, monitor blast symptoms and avoid standing water."),
    "groundnut": crop_item("Groundnut", "ବାଦାମ", "Oilseed", "Arachis hypogaea", "Kharif / Rabi", "Sandy loam", "Leaf Miner, White Grub", "Tikka Leaf Spot, Rust", 7, (24, 33), 75, 9, "Ensure drainage, rotate crops and scout for leaf spots during humid days."),
    "mustard": crop_item("Mustard", "ସୋରିଷ", "Oilseed", "Brassica juncea", "Rabi", "Loam to clay loam", "Aphids, Painted Bug", "Alternaria Blight, White Rust", 6, (15, 28), 72, 6, "Monitor aphids early, avoid overhead irrigation and maintain crop spacing."),
    "cotton": crop_item("Cotton", "କପା", "Fiber", "Gossypium hirsutum", "Kharif", "Black cotton soil / loam", "Bollworm, Whitefly, Jassid", "Leaf Curl, Wilt", 8, (25, 35), 76, 8, "Use sticky traps, monitor whitefly and avoid excess nitrogen."),
    "sugarcane": crop_item("Sugarcane", "ଆଖୁ", "Cash crop", "Saccharum officinarum", "Annual", "Deep fertile loam", "Early Shoot Borer, Pyrilla", "Red Rot, Smut", 8, (25, 36), 80, 10, "Use healthy setts, remove infected clumps and maintain drainage."),
    "tomato": crop_item("Tomato", "ଟମାଟୋ", "Vegetable", "Solanum lycopersicum", "Rabi / Summer", "Well-drained loam", "Fruit Borer, Whitefly, Aphids", "Early Blight, Late Blight, Leaf Curl", 9, (20, 32), 72, 7, "Stake plants, remove infected leaves, avoid wet foliage and monitor whitefly."),
    "potato": crop_item("Potato", "ଆଳୁ", "Vegetable", "Solanum tuberosum", "Rabi", "Loose sandy loam", "Aphids, Cutworm", "Late Blight, Early Blight", 9, (15, 25), 70, 5, "Watch for late blight after cloudy humid weather and avoid waterlogging."),
    "brinjal": crop_item("Brinjal", "ବାଇଗଣ", "Vegetable", "Solanum melongena", "All season", "Fertile well-drained loam", "Shoot and Fruit Borer, Aphids", "Wilt, Leaf Spot", 8, (22, 34), 74, 7, "Remove borer-damaged shoots/fruits, use pheromone traps and clean the field."),
    "eggplant": "brinjal",
    "okra": crop_item("Okra", "ଭେଣ୍ଡି", "Vegetable", "Abelmoschus esculentus", "Summer / Rainy", "Sandy loam", "Jassid, Whitefly, Fruit Borer", "Yellow Vein Mosaic, Powdery Mildew", 8, (24, 35), 75, 8, "Monitor jassid/whitefly and remove infected yellow mosaic plants early."),
    "lady finger": "okra",
    "chilli": crop_item("Chilli", "ଲଙ୍କା", "Vegetable", "Capsicum annuum", "Rabi / Summer", "Well-drained loam", "Thrips, Mites, Aphids", "Leaf Curl, Anthracnose", 8, (20, 32), 72, 7, "Check curling leaves, manage thrips/mites early and maintain drainage."),
    "cabbage": crop_item("Cabbage", "ବନ୍ଧାକୋବି", "Vegetable", "Brassica oleracea var. capitata", "Rabi", "Fertile loam", "Diamondback Moth, Aphids", "Black Rot, Downy Mildew", 7, (15, 25), 74, 6, "Use clean seedlings, avoid water splash and scout diamondback moth."),
    "cauliflower": crop_item("Cauliflower", "ଫୁଲକୋବି", "Vegetable", "Brassica oleracea var. botrytis", "Rabi", "Fertile loam", "Diamondback Moth, Leaf Webber", "Black Rot, Club Root", 7, (15, 25), 74, 6, "Maintain soil health and spacing, and remove infected plant debris."),
    "onion": crop_item("Onion", "ପିଆଜ", "Vegetable", "Allium cepa", "Rabi", "Sandy loam", "Thrips, Onion Maggot", "Purple Blotch, Downy Mildew", 7, (18, 30), 73, 5, "Avoid excess moisture, monitor thrips and purple blotch."),
    "pumpkin": crop_item("Pumpkin", "କଖାରୁ", "Vegetable", "Cucurbita maxima", "Summer / Rainy", "Sandy loam", "Fruit Fly, Red Pumpkin Beetle", "Powdery Mildew, Downy Mildew", 6, (24, 35), 78, 9, "Use traps for fruit fly, keep vines aerated and avoid wet foliage."),
    "cucumber": crop_item("Cucumber", "କାକୁଡି", "Vegetable", "Cucumis sativus", "Summer", "Sandy loam", "Fruit Fly, Aphids", "Powdery Mildew, Mosaic", 7, (24, 34), 76, 8, "Use trellis where possible and monitor aphids and mildew."),
    "bitter gourd": crop_item("Bitter Gourd", "କଲରା", "Vegetable", "Momordica charantia", "Summer / Rainy", "Sandy loam", "Fruit Fly, Beetles", "Powdery Mildew, Mosaic", 7, (24, 35), 76, 8, "Use fruit fly traps, remove damaged fruits and maintain field sanitation."),
    "bottle gourd": crop_item("Bottle Gourd", "ଲାଉ", "Vegetable", "Lagenaria siceraria", "Summer / Rainy", "Sandy loam", "Fruit Fly, Aphids", "Downy Mildew, Mosaic", 7, (24, 35), 77, 9, "Keep vines clean and monitor underside of leaves and fruit fly."),
    "mango": crop_item("Mango", "ଆମ୍ବ", "Fruit", "Mangifera indica", "Perennial", "Deep well-drained loam", "Mango Hopper, Fruit Fly", "Anthracnose, Powdery Mildew", 7, (24, 36), 78, 10, "Monitor hopper during flowering and anthracnose during humid periods."),
    "banana": crop_item("Banana", "କଦଳୀ", "Fruit", "Musa paradisiaca", "Perennial", "Rich loamy soil", "Banana Weevil, Aphids", "Panama Wilt, Sigatoka", 8, (24, 35), 78, 10, "Ensure drainage, remove diseased leaves and use clean planting material."),
    "papaya": crop_item("Papaya", "ଅମୃତଭଣ୍ଡା", "Fruit", "Carica papaya", "Perennial", "Well-drained loam", "Mealybug, Aphids", "Leaf Curl, Ring Spot", 7, (22, 34), 76, 8, "Control vectors and remove infected plants early."),
    "coconut": crop_item("Coconut", "ନଡ଼ିଆ", "Fruit", "Cocos nucifera", "Perennial", "Sandy coastal soil", "Rhinoceros Beetle, Red Palm Weevil", "Bud Rot, Leaf Blight", 7, (25, 36), 80, 12, "Monitor crown and trunk, keep basin clean and check for beetle damage."),
    "watermelon": crop_item("Watermelon", "ତରଭୁଜ", "Fruit", "Citrullus lanatus", "Summer", "Sandy loam", "Fruit Fly, Aphids", "Powdery Mildew, Wilt", 6, (24, 35), 76, 8, "Use healthy seedlings, avoid waterlogging and monitor fruit fly."),
}


def resolve_crop(crop_name: str | None) -> tuple[dict[str, Any], str]:
    """Resolve a crop name/alias to its knowledge record.

    Unknown names resolve to a transparent general profile so user input is
    never silently dropped.
    """
    key = (crop_name or "").strip().lower()
    value = CROPS.get(key)
    if isinstance(value, str):
        key = value
        value = CROPS.get(value)
    if value:
        return value, key
    display_name = crop_name.strip().title() if crop_name else "General Crop"
    return _general_crop(display_name), key or "general"


def crop_display_names() -> list[str]:
    """Sorted unique display names for the crop datalist."""
    return sorted({v["name"] for v in CROPS.values() if isinstance(v, dict)})


__all__ = [
    "CROPS",
    "GROWTH_STAGES",
    "FIELD_CONDITIONS",
    "crop_item",
    "resolve_crop",
    "crop_display_names",
]
