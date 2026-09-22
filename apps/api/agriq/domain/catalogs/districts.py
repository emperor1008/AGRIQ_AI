"""Odisha district geodata and agro-climatic profiles (ARC-04)."""
from __future__ import annotations

from typing import Mapping

# district -> (latitude, longitude)
DISTRICTS: dict[str, tuple[float, float]] = {
    "Cuttack": (20.4625, 85.8830),
    "Puri": (19.8135, 85.8312),
    "Jajpur": (20.8550, 86.3370),
    "Jagatsinghpur": (20.2540, 86.1710),
    "Khordha": (20.1820, 85.6160),
    "Ganjam": (19.3140, 84.7940),
    "Balasore": (21.4940, 86.9330),
    "Bhadrak": (21.0540, 86.5150),
    "Sambalpur": (21.4700, 83.9700),
    "Sundargarh": (22.1200, 84.0300),
    "Mayurbhanj": (21.9000, 86.7300),
    "Koraput": (18.8130, 82.7100),
    "Kalahandi": (19.9070, 83.1640),
    "Angul": (20.8400, 85.1500),
    "Bargarh": (21.3300, 83.6200),
    "Balangir": (20.7160, 83.4850),
    "Dhenkanal": (20.6570, 85.6000),
    "Nayagarh": (20.1280, 85.0960),
    "Keonjhar": (21.6280, 85.5810),
    "Rayagada": (19.1730, 83.4160),
    "Kendrapara": (20.5000, 86.4200),
    "Nabarangpur": (19.2300, 82.5500),
    "Nuapada": (20.8100, 82.5300),
    "Deogarh": (21.5300, 84.7330),
    "Jharsuguda": (21.8550, 84.0060),
    "Boudh": (20.8300, 84.3200),
    "Subarnapur": (20.8500, 83.9000),
    "Gajapati": (19.1700, 84.1200),
    "Kandhamal": (20.4800, 84.2300),
    "Malkangiri": (18.3500, 81.9000),
}

COASTAL_DISTRICTS: set[str] = {
    "Puri", "Kendrapara", "Jagatsinghpur", "Cuttack", "Balasore",
    "Bhadrak", "Ganjam", "Khordha", "Jajpur",
}
HIGHLAND_DISTRICTS: set[str] = {
    "Koraput", "Kandhamal", "Rayagada", "Gajapati", "Malkangiri", "Nabarangpur",
}
WESTERN_DISTRICTS: set[str] = {
    "Kalahandi", "Balangir", "Bargarh", "Nuapada", "Subarnapur",
    "Sambalpur", "Jharsuguda", "Sundargarh", "Boudh",
}

DISTRICT_PROFILES: dict[str, Mapping[str, str]] = {
    "Cuttack": {
        "zone": "Coastal alluvial command belt",
        "soil": "Alluvial / clay loam",
        "main": "Rice, vegetables, pulses",
        "stress": "Flooding and humidity-driven disease",
    },
    "Puri": {
        "zone": "Coastal sandy-alluvial belt",
        "soil": "Sandy coastal + alluvial",
        "main": "Rice, coconut, vegetables",
        "stress": "Cyclone exposure, salinity and waterlogging",
    },
    "Kendrapara": {
        "zone": "Coastal delta belt",
        "soil": "Alluvial with saline patches",
        "main": "Rice, jute, vegetables",
        "stress": "Salinity and flood-prone crop stress",
    },
    "Jagatsinghpur": {
        "zone": "Mahanadi delta belt",
        "soil": "Alluvial / clay loam",
        "main": "Rice, pulses, vegetables",
        "stress": "High humidity and waterlogging",
    },
    "Ganjam": {
        "zone": "Southern coastal belt",
        "soil": "Red, laterite and coastal alluvial",
        "main": "Rice, groundnut, vegetables",
        "stress": "Heat, dry spell and cyclone exposure",
    },
    "Koraput": {
        "zone": "Eastern Ghats highland",
        "soil": "Red and lateritic hill soil",
        "main": "Millets, rice, coffee",
        "stress": "Slope moisture stress and local pest pockets",
    },
    "Kalahandi": {
        "zone": "Western undulating belt",
        "soil": "Red and mixed soil",
        "main": "Rice, cotton, pulses",
        "stress": "Dry spell and heat stress",
    },
    "Mayurbhanj": {
        "zone": "Northern plateau belt",
        "soil": "Red and laterite soil",
        "main": "Rice, maize, oilseeds",
        "stress": "Mixed plateau climate risk",
    },
    "Sambalpur": {
        "zone": "Western irrigation belt",
        "soil": "Red and alluvial mixed soil",
        "main": "Rice, pulses, vegetables",
        "stress": "Heat stress with irrigation-dependent crops",
    },
    "Balasore": {
        "zone": "Northern coastal belt",
        "soil": "Alluvial and coastal sandy loam",
        "main": "Rice, jute, vegetables",
        "stress": "Humidity, waterlogging and leaf disease pressure",
    },
}

DEFAULT_PROFILE: Mapping[str, str] = {
    "zone": "Odisha agro-climatic belt",
    "soil": "Red / laterite / alluvial mixed soil",
    "main": "Rice, pulses, vegetables",
    "stress": "Seasonal pest and disease pressure",
}


def profile_for(district: str) -> Mapping[str, str]:
    """Return the curated agro-climatic profile for a district."""
    return DISTRICT_PROFILES.get(district, DEFAULT_PROFILE)


def coordinates_for(district: str) -> tuple[float, float]:
    """Return (lat, lon) for a district, defaulting to Cuttack."""
    return DISTRICTS.get(district, DISTRICTS["Cuttack"])


__all__ = [
    "DISTRICTS",
    "DISTRICT_PROFILES",
    "DEFAULT_PROFILE",
    "COASTAL_DISTRICTS",
    "HIGHLAND_DISTRICTS",
    "WESTERN_DISTRICTS",
    "profile_for",
    "coordinates_for",
]
