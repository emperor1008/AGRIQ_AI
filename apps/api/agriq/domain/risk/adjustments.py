"""Growth-stage and field-condition adjustment rules used by risk scoring."""
from __future__ import annotations


def growth_stage_adjustment(stage: str | None) -> float:
    """Risk contribution of the crop growth stage (0-6)."""
    stage = (stage or "").lower()
    if "flower" in stage:
        return 5
    if "fruit" in stage or "grain" in stage:
        return 6
    if "vegetative" in stage:
        return 4
    if "seedling" in stage:
        return 3
    if "harvest" in stage:
        return 1
    return 2


def field_condition_adjustment(condition: str | None) -> float:
    """Risk contribution of the reported field condition (0-9)."""
    condition = (condition or "").lower()
    if "waterlogged" in condition:
        return 8
    if "leaf spot" in condition:
        return 9
    if "pest" in condition:
        return 8
    if "humid" in condition:
        return 6
    if "dry" in condition:
        return 4
    return 0


__all__ = ["growth_stage_adjustment", "field_condition_adjustment"]
