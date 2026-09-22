"""Soil reference library for student learning and advisory context."""
from __future__ import annotations

SOIL_LIBRARY: dict[str, dict[str, str]] = {
    "Alluvial soil": {"features": "Fertile, good for rice, wheat, vegetables and pulses.", "problems": "Flooding, nutrient leaching and zinc deficiency can occur.", "management": "Use soil-test-based fertilizer, organic matter, drainage and crop rotation."},
    "Red soil": {"features": "Common in uplands; usually low in nitrogen, phosphorus and organic matter.", "problems": "Low water holding capacity and acidity in some patches.", "management": "Add FYM/compost, lime if acidic, mulching and balanced NPK."},
    "Laterite soil": {"features": "Found in high rainfall zones; iron-rich and often acidic.", "problems": "Low fertility and phosphorus fixation.", "management": "Use organic matter, liming, contour bunding and suitable crops like cashew, millets and tubers."},
    "Black soil": {"features": "Clayey, high water holding capacity, suitable for cotton and pulses.", "problems": "Cracking, poor drainage and difficult tillage when wet.", "management": "Use proper drainage, broad-bed furrow and timely tillage."},
    "Sandy soil": {"features": "Light soil with quick drainage, useful for vegetables and groundnut.", "problems": "Low nutrient and water holding capacity.", "management": "Use frequent light irrigation, compost, mulching and split fertilizer doses."},
    "Clay loam": {"features": "Good moisture retention; suitable for rice and vegetables.", "problems": "Waterlogging if drainage is poor.", "management": "Maintain drainage channels and avoid working when too wet."},
    "Saline soil": {"features": "High soluble salts reduce crop growth.", "problems": "Poor germination and leaf tip burning.", "management": "Use salt-tolerant crops, good-quality irrigation water, drainage and gypsum where recommended."},
}

__all__ = ["SOIL_LIBRARY"]
