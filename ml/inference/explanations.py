"""Farmer-friendly explanations and limitations (Phase 4).

Explanation strings are **categorical** (based on the predicted class and
quality metrics), never fabricated image-specific claims. Grad-CAM is not
implemented in Phase 4 — when it is, it must be labelled as model attention,
not biological causation.
"""
from __future__ import annotations

from typing import Any

# Display names for AGRIQ condition codes (English; the API layer localises).
DISPLAY_NAMES: dict[str, str] = {
    "rice_healthy": "Healthy rice leaf",
    "rice_blast": "Possible rice blast",
    "rice_bacterial_leaf_blight": "Possible bacterial leaf blight",
    "rice_brown_spot": "Possible brown spot",
    "rice_tungro": "Possible tungro",
    "rice_unknown": "Unrecognised rice condition",
    "tomato_healthy": "Healthy tomato leaf",
    "tomato_early_blight": "Possible early blight",
    "tomato_late_blight": "Possible late blight",
    "tomato_leaf_mould": "Possible leaf mould",
    "tomato_leaf_curl": "Possible leaf curl",
    "tomato_unknown": "Unrecognised tomato condition",
}

# Pattern-based explanations keyed by condition family. Each entry describes
# the general pattern the model considers — not a claim about THIS image.
PATTERNS: dict[str, list[str]] = {
    "rice_blast": [
        "Visible lesion patterns overlap with examples of blast in the validated model classes (spindle-shaped lesions with grey centres).",
    ],
    "rice_bacterial_leaf_blight": [
        "Yellowing from leaf tips with wavy margins overlaps with validated bacterial leaf blight examples.",
    ],
    "rice_brown_spot": [
        "Round to oval brown spots visible in the pattern overlap with validated brown-spot examples.",
    ],
    "rice_tungro": [
        "Yellow-orange discolouration and stunted appearance overlap with validated tungro examples.",
    ],
    "tomato_early_blight": [
        "Concentric-ring (target-spot) lesions overlap with validated early-blight examples.",
    ],
    "tomato_late_blight": [
        "Greasy, irregular water-soaked lesions overlap with validated late-blight examples.",
    ],
    "tomato_leaf_mould": [
        "Yellow upper-surface patches overlap with validated leaf-mould examples.",
    ],
    "tomato_leaf_curl": [
        "Leaf-curling and yellowing patterns overlap with validated leaf-curl examples.",
    ],
    "rice_healthy": ["The leaf pattern matches healthy examples in the validated model classes."],
    "tomato_healthy": ["The leaf pattern matches healthy examples in the validated model classes."],
}

LIMITATIONS = [
    "Image screening cannot confirm a laboratory diagnosis.",
    "Other diseases can look similar on a leaf; expert confirmation is required before any treatment.",
    "Model validation for local field conditions is in progress.",
]


def explanation_for(condition: str) -> list[str]:
    return list(PATTERNS.get(condition, ["The pattern was compared against validated model examples."]))


def display_name(condition: str) -> str:
    return DISPLAY_NAMES.get(condition, condition.replace("_", " ").title())


def limitations() -> list[str]:
    return list(LIMITATIONS)
