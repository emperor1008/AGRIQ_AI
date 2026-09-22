"""Crop-cycle advisory engine (Phase 2 §10).

For each growth stage the engine returns a structured advisory skeleton:
current objective, what to observe, possible action families, weather
considerations and safety limitations. Actions are families ("inspect field
moisture"), never exact chemical/fertiliser quantities — those require
approved regional evidence which only the retriever can supply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class StageAdvisory:
    """Structured advisory for one crop-cycle stage."""

    stage: str
    objective: str
    recommended_observations: list[str] = field(default_factory=list)
    possible_actions: list[str] = field(default_factory=list)
    weather_considerations: list[str] = field(default_factory=list)
    safety_limitations: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    follow_up_days: int = 7

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "objective": self.objective,
            "recommended_observations": list(self.recommended_observations),
            "possible_actions": list(self.possible_actions),
            "weather_considerations": list(self.weather_considerations),
            "safety_limitations": list(self.safety_limitations),
            "missing_information": list(self.missing_information),
            "follow_up_days": self.follow_up_days,
        }


# Stage keys align with the crop-stage reference used by the Phase 1
# crop_stage_service (land preparation → post harvest).
_ADVISORIES: dict[str, StageAdvisory] = {
    "land_preparation": StageAdvisory(
        stage="Land preparation",
        objective="Prepare a fine, level seedbed or puddled field suited to the crop and season.",
        recommended_observations=["field wetness", "residue from previous crop", "weed emergence"],
        possible_actions=["Check bund integrity", "Plan tillage around rainfall forecast"],
        weather_considerations=["Heavy rain can delay tillage", "Dry spells help land drying"],
        safety_limitations=["Machinery safety on wet fields"],
        follow_up_days=5,
    ),
    "seed_preparation": StageAdvisory(
        stage="Seed/variety preparation",
        objective="Use verified seed of a variety suited to the season and local advisory.",
        recommended_observations=["seed germination rate in a small test"],
        possible_actions=["Confirm variety with local KVK advisory", "Check seed source documentation"],
        weather_considerations=["Avoid seed exposure to excess heat or moisture"],
        safety_limitations=["No seed treatment dosage without approved evidence"],
        missing_information=["variety", "seed source"],
        follow_up_days=7,
    ),
    "sowing_transplanting": StageAdvisory(
        stage="Sowing/Transplanting",
        objective="Establish the crop at the recommended window with adequate soil moisture.",
        recommended_observations=["soil moisture at seed depth", "rainfall in the coming days"],
        possible_actions=["Inspect field moisture before sowing", "Record sowing date in AGRIQ"],
        weather_considerations=["Rain before sowing improves establishment", "Heat stress on seedlings"],
        safety_limitations=["No exact seed rate without approved regional recommendation"],
        follow_up_days=3,
    ),
    "establishment": StageAdvisory(
        stage="Establishment",
        objective="Secure uniform stand; identify gaps early.",
        recommended_observations=["gap %", "seedling vigour", "standing water level (paddy)"],
        possible_actions=["Walk the field and count gaps", "Record establishment observation"],
        weather_considerations=["Heavy rain right after sowing can crust the soil"],
        safety_limitations=["Re-sowing decisions need field inspection"],
        follow_up_days=4,
    ),
    "vegetative": StageAdvisory(
        stage="Vegetative growth",
        objective="Build healthy canopy; monitor nutrient and pest symptoms early.",
        recommended_observations=["leaf colour", "pest incidence on leaves and stems", "weed pressure"],
        possible_actions=["Inspect field moisture before irrigating", "Record any yellowing or spots with a photo-free note"],
        weather_considerations=["Rain may reduce irrigation need", "Humid spells favour disease-conducive conditions"],
        safety_limitations=["Nutrient correction needs a soil test value"],
        follow_up_days=5,
    ),
    "tillering": StageAdvisory(
        stage="Tillering",
        objective="Maximise productive tillers without lodging risk.",
        recommended_observations=["tillers per hill", "leaf colour", "water level"],
        possible_actions=["Inspect field moisture before irrigating", "Note lodging-prone patches"],
        weather_considerations=["Rain before irrigation may make it unnecessary"],
        safety_limitations=["Fertiliser top-up quantity requires soil test + approved advisory"],
        follow_up_days=5,
    ),
    "flowering": StageAdvisory(
        stage="Flowering",
        objective="Protect the flowering window from moisture and heat stress.",
        recommended_observations=["flower opening", "moisture stress signs", "pest on panicles"],
        possible_actions=["Avoid spraying during flowering where pollinators are active", "Watch forecast for rain at heading"],
        weather_considerations=["Rain during flowering affects grain set", "Heat above crop tolerance reduces set"],
        safety_limitations=["Spray advice requires fresh safe-weather verification"],
        follow_up_days=3,
    ),
    "fruiting_grain_filling": StageAdvisory(
        stage="Fruiting/Grain formation",
        objective="Maintain steady moisture and protect the filling grain.",
        recommended_observations=["grain filling", "irrigation need", "bird/pest pressure"],
        possible_actions=["Inspect field moisture before irrigating", "Record any panicle damage"],
        weather_considerations=["Dry spell during filling reduces yield", "Rain near harvest delays cutting"],
        safety_limitations=["No pre-harvest chemical use without label interval check"],
        follow_up_days=4,
    ),
    "maturity": StageAdvisory(
        stage="Maturity",
        objective="Decide harvest timing on grain moisture and forecast, not on a fixed date alone.",
        recommended_observations=["grain hardness", "leaf senescence", "forecast rain window"],
        possible_actions=["Plan harvest around a dry forecast window", "Arrange threshing/drying capacity"],
        weather_considerations=["Rain at maturity risks sprouting", "Wind can lodge the crop"],
        safety_limitations=["Do not cut and store grain above safe moisture without drying"],
        follow_up_days=2,
    ),
    "harvest": StageAdvisory(
        stage="Harvest",
        objective="Complete cutting and threshing with minimal loss.",
        recommended_observations=["actual moisture", "field access", "labour/machinery availability"],
        possible_actions=["Cut in the driest window", "Record harvest date and approximate condition"],
        weather_considerations=["Avoid wet cutting", "Heat safety during operations"],
        safety_limitations=["Machinery operator safety"],
        follow_up_days=2,
    ),
    "post_harvest": StageAdvisory(
        stage="Post-harvest",
        objective="Dry and store safely; preserve quality for market.",
        recommended_observations=["storage moisture", "pest in storage"],
        possible_actions=["Dry to a safe storage level before storage", "Monitor storage regularly"],
        weather_considerations=["Sun-drying depends on clear weather"],
        safety_limitations=["No storage-chemical advice without label support"],
        follow_up_days=10,
    ),
}


def stage_advisory(stage_key: Optional[str], crop: Optional[str] = None) -> StageAdvisory:
    """Return the advisory skeleton for a stage (crop-agnostic core)."""
    if not stage_key:
        return StageAdvisory(
            stage="Unknown",
            objective="Confirm the crop stage before following any stage-specific guidance.",
            recommended_observations=["confirm the current growth stage in the field"],
            possible_actions=["Confirm the crop stage in AGRIQ"],
            missing_information=["crop stage"],
        )
    advisory = _ADVISORIES.get(stage_key) or _ADVISORIES.get(stage_key.lower())
    if advisory is None:
        # Map legacy stage labels onto engine keys where possible.
        lowered = stage_key.lower()
        for key in _ADVISORIES:
            if key.split("_")[0] in lowered or lowered in key:
                advisory = _ADVISORIES[key]
                break
    if advisory is None:
        return StageAdvisory(
            stage=stage_key,
            objective="General care: monitor the field and record observations.",
            recommended_observations=["field condition", "pest or disease symptoms"],
            possible_actions=["Record a field observation in AGRIQ"],
            missing_information=["crop stage reference"],
        )
    return advisory


__all__ = ["StageAdvisory", "stage_advisory"]
