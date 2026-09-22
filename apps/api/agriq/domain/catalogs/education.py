"""Education/academic reference catalogues for the Student/Research workspace.

Contains study areas, academic levels, purposes, depths, plant categories,
farming methods, animal library, semester guide, per-domain field config and
the small teaching banks (fertilizer, weeds, seed, irrigation, career).
"""
from __future__ import annotations

from typing import Any, Mapping

from .diseases import DISEASE_LIBRARY
from .pests import PEST_LIBRARY

STUDENT_AREAS: dict[str, list[str]] = {
    "Agronomy": [
        "Principles of Agronomy", "Tillage and Tilth", "Seed Rate and Spacing", "Cropping Systems",
        "Irrigation Scheduling", "Weed Management", "Integrated Nutrient Management", "Dryland Agriculture",
        "Organic and Natural Farming", "Precision Farming", "Climate Smart Agriculture", "Practical Crop Production",
    ],
    "Soil Science": [
        "Soil Formation", "Soil Texture and Structure", "Soil pH and EC", "Soil Organic Carbon",
        "NPK and Micronutrients", "Manures and Fertilizers", "Soil Health Card", "Soil Water Conservation",
        "Problem Soils", "Soil Sampling", "Biofertilizers", "Composting and Vermicomposting",
    ],
    "Entomology": [
        "Insect Morphology", "Insect Life Cycle", "Economic Threshold Level", "Major Crop Pests",
        "Sucking Pests", "Borers and Fruit Flies", "Biological Control", "Pheromone and Sticky Traps",
        "Insecticide Resistance", "Integrated Pest Management", "Beneficial Insects", "Storage Grain Pests",
    ],
    "Plant Pathology": [
        "Plant Disease Triangle", "Fungal Diseases", "Bacterial Diseases", "Viral Diseases", "Nematode Diseases",
        "Disease Diagnosis", "Disease Epidemiology", "Seed-borne Diseases", "Post Harvest Diseases",
        "Biological Control", "Integrated Disease Management", "Plant Quarantine",
    ],
    "Horticulture": [
        "Pomology Fruit Science", "Olericulture Vegetable Science", "Floriculture", "Nursery Management",
        "Training and Pruning", "Orchard Layout", "Propagation Methods", "Protected Cultivation",
        "Post Harvest Management", "Value Addition", "Kitchen Garden", "Plantation Crops",
    ],
    "Genetics & Plant Breeding": [
        "Mendelian Genetics", "Pollination and Reproduction", "Selection Methods", "Hybridization",
        "Pure Line and Mass Selection", "Heterosis", "Mutation Breeding", "Marker Assisted Selection",
        "Seed Certification", "Varietal Evaluation", "Germplasm Conservation", "Breeding for Resistance",
    ],
    "Seed Science": [
        "Seed Structure", "Seed Germination", "Seed Dormancy", "Seed Testing", "Seed Vigor",
        "Seed Processing", "Seed Storage", "Seed Certification", "Seed Treatment", "Seed Production Techniques",
    ],
    "Crop Physiology": [
        "Photosynthesis", "Respiration", "Transpiration", "Source Sink Relationship", "Growth Analysis",
        "Plant Growth Regulators", "Stress Physiology", "Drought Stress", "Flowering and Photoperiodism", "Harvest Index",
    ],
    "Agricultural Economics": [
        "Cost of Cultivation", "Farm Budgeting", "Demand and Supply", "Marketable Surplus", "MSP and Mandi",
        "Benefit Cost Ratio", "Risk and Uncertainty", "Crop Insurance", "Value Chain", "Agri Entrepreneurship",
    ],
    "Extension Education": [
        "Extension Teaching Methods", "Rural Sociology", "Adoption and Diffusion", "Communication Models",
        "KVK and Farm Advisory", "Farmer Field School", "ICT in Agriculture", "Participatory Rural Appraisal",
    ],
    "Agricultural Engineering": [
        "Farm Machinery", "Tillage Implements", "Irrigation Systems", "Sprinkler and Drip Irrigation",
        "Post Harvest Equipment", "Renewable Energy", "Protected Structures", "IoT Sensors in Agriculture",
    ],
    "Remote Sensing & GIS": [
        "NDVI Crop Health", "Disease Hotspot Mapping", "Yield Prediction", "Drought Risk Mapping",
        "Land Use Mapping", "GPS Field Survey", "Drone Agriculture", "GIS Layers", "Satellite Image Interpretation",
    ],
    "Animal Husbandry & Fisheries": [
        "Dairy Management", "Poultry Management", "Goat Farming", "Sheep Farming", "Fish Farming",
        "Animal Nutrition", "Housing and Sanitation", "Vaccination Schedule", "Breed Selection", "Fodder Production",
    ],
    "Agroforestry & Forestry": [
        "Agroforestry Systems", "Multipurpose Trees", "Windbreak and Shelterbelt", "Silviculture Basics",
        "Tree Nursery", "Social Forestry", "Carbon Sequestration", "Soil Conservation Trees",
    ],
    "Food & Post Harvest": [
        "Post Harvest Losses", "Grading and Packaging", "Storage Structures", "Drying and Dehydration",
        "Value Addition", "Cold Chain", "Processing of Fruits and Vegetables", "Quality Parameters",
    ],
}

ACADEMIC_LEVELS: list[str] = [
    "Diploma / Foundation", "B.Sc Agriculture Semester 1-2", "B.Sc Agriculture Semester 3-4",
    "B.Sc Agriculture Semester 5-6", "B.Sc Agriculture Semester 7-8", "M.Sc / ICAR-JRF Level", "Research Project / Thesis Level",
]

STUDY_PURPOSES: list[str] = [
    "Exam Preparation", "Viva / Oral Exam", "Practical File", "Assignment Writing", "Research Proposal",
    "Field Survey", "Competitive Exam Revision", "Concept Understanding", "Presentation / Seminar",
]

STUDY_DEPTHS: list[str] = ["Simple", "Detailed", "Exam-Oriented", "Research-Oriented", "Field Practical"]

PLANT_CATEGORIES: dict[str, list[str]] = {
    "Cereals": ["Rice", "Wheat", "Maize", "Ragi"],
    "Pulses": ["Green gram", "Black gram", "Pigeon pea", "Chickpea", "Lentil"],
    "Oilseeds": ["Groundnut", "Mustard", "Sesame", "Sunflower"],
    "Vegetables": ["Tomato", "Potato", "Brinjal", "Okra", "Chilli", "Cabbage", "Cauliflower", "Onion", "Pumpkin", "Cucumber"],
    "Fruits": ["Mango", "Banana", "Papaya", "Coconut", "Watermelon", "Guava", "Citrus", "Jackfruit"],
    "Plantation / Trees": ["Coconut", "Cashew", "Arecanut", "Teak", "Neem", "Bamboo", "Eucalyptus", "Drumstick"],
}

FARMING_METHODS: dict[str, str] = {
    "Conventional farming": "Uses standard tillage, fertilizer and pest management. Study focus: input efficiency, yield and cost of cultivation.",
    "Organic farming": "Avoids synthetic inputs and uses compost, biofertilizers, crop rotation and biological pest management.",
    "Natural farming": "Focuses on local inputs, soil biological activity, mulching and reduced external dependency.",
    "Integrated farming system": "Combines crop, livestock, fishery, poultry, composting and recycling of farm waste.",
    "Precision farming": "Uses sensors, GPS, GIS, drones and data-driven input application.",
    "Protected cultivation": "Uses polyhouse/net house/shade structures to manage microclimate and produce high-value crops.",
    "Agroforestry": "Integrates trees with crops/livestock for soil conservation, fodder, fuel, timber and climate resilience.",
    "SRI / SCI method": "Uses young seedlings, wider spacing, water management and soil aeration to improve crop productivity.",
}

ANIMAL_LIBRARY: dict[str, dict[str, str]] = {
    "Dairy cattle": {"focus": "Milk production, breed selection, feed, housing and clean milking.", "records": "Milk yield, feed intake, heat signs, vaccination, deworming and disease history.", "exam": "Explain balanced ration, clean water, housing ventilation, mastitis prevention and calf care.", "research": "Compare feeding practice, housing hygiene or milk yield under different management systems."},
    "Buffalo": {"focus": "High-fat milk, heat stress management, wallowing/cooling and reproductive care.", "records": "Milk fat, lactation stage, feed, heat detection and health records.", "exam": "Mention cooling, mineral mixture, fodder quality and clean milking.", "research": "Study relation between heat stress, cooling practice and milk yield."},
    "Goat": {"focus": "Breed, housing, browsing, kid care, vaccination and smallholder income.", "records": "Body weight, kidding, mortality, feed, deworming and vaccination.", "exam": "Write about raised housing, clean floor, fodder trees and disease prevention.", "research": "Survey growth performance or economics of goat farming systems."},
    "Poultry": {"focus": "Brooding, feed conversion, litter management, vaccination and egg/meat production.", "records": "Body weight, feed intake, mortality, egg production, temperature and vaccination.", "exam": "Explain brooding temperature, litter quality, clean water and vaccination schedule.", "research": "Analyse feed conversion ratio, mortality or egg production under different housing."},
    "Fish": {"focus": "Pond preparation, stocking density, water quality, feeding and disease prevention.", "records": "pH, dissolved oxygen, stocking number, feed, growth and mortality.", "exam": "Mention pond liming, fertilization, seed quality, feed and water quality.", "research": "Study water quality effect on fish growth or survival."},
}

FIELD_PROBLEM_OPTIONS: list[str] = [
    "Leaf spots", "Yellowing", "Wilting", "Stunting", "Leaf curling", "Fruit damage", "Stem boring", "Root damage",
    "Low germination", "Nutrient deficiency", "Waterlogging", "Drought stress", "Animal health issue", "Low milk/egg/fish production",
]

OUTPUT_FORMATS: list[str] = ["Semester Notes", "Important Questions", "Assignment Questions", "MCQ Practice", "Viva Sheet", "Research Plan", "Practical Record", "Field Diagnosis", "Presentation Points"]

SEMESTER_WISE_GUIDE: dict[str, list[str]] = {
    "B.Sc Agriculture Semester 1-2": [
        "Fundamentals of Agronomy", "Agricultural Heritage", "Introductory Soil Science",
        "Fundamentals of Horticulture", "Rural Sociology", "Introductory Biology / Botany",
        "Agricultural Meteorology", "Communication Skills",
    ],
    "B.Sc Agriculture Semester 3-4": [
        "Crop Production Technology", "Soil Fertility and Nutrient Management", "Agricultural Microbiology",
        "Principles of Plant Pathology", "Principles of Entomology", "Genetics", "Farm Machinery",
        "Water Management", "Weed Management",
    ],
    "B.Sc Agriculture Semester 5-6": [
        "Field Crop Production", "Plant Breeding", "Seed Technology", "Integrated Pest Management",
        "Integrated Disease Management", "Horticultural Crop Production", "Agricultural Economics",
        "Extension Education", "Protected Cultivation",
    ],
    "B.Sc Agriculture Semester 7-8": [
        "RAWE / Experiential Learning", "Agri-business Management", "Project Work", "Field Survey",
        "Entrepreneurship", "Precision Farming", "Post Harvest Management", "Seminar and Report Writing",
    ],
    "M.Sc / ICAR-JRF Level": [
        "Advanced subject theory", "Research methodology", "Experimental design", "Statistical analysis",
        "Review paper writing", "Scientific presentation", "Objective question practice", "Recent advances",
    ],
    "Research Project / Thesis Level": [
        "Problem identification", "Literature review", "Objectives and hypothesis", "Sampling design",
        "Data collection tools", "Statistical analysis", "Result interpretation", "Thesis writing and citation ethics",
    ],
    "Diploma / Foundation": [
        "Basic crop production", "Soil and fertilizer basics", "Pest and disease identification",
        "Irrigation and drainage", "Seed and nursery management", "Farm tools", "Practical record writing",
    ],
}

FERTILIZER_IDENTIFICATION: list[dict[str, str]] = [
    {"name": "Urea", "nutrient": "Nitrogen source", "field_id": "White granules/prills; highly soluble", "safe_note": "Use split application and avoid excess nitrogen."},
    {"name": "DAP", "nutrient": "Nitrogen + phosphorus source", "field_id": "Dark grey/black hard granules", "safe_note": "Mostly basal application; final dose should follow soil test."},
    {"name": "MOP", "nutrient": "Potassium source", "field_id": "Pink/red/white crystalline granules", "safe_note": "Useful where soil K is low; avoid direct seed contact."},
    {"name": "SSP", "nutrient": "Phosphorus + sulphur source", "field_id": "Grey powder/granules", "safe_note": "Good for sulphur-demanding crops; apply according to recommendation."},
    {"name": "Zinc sulphate", "nutrient": "Zinc micronutrient", "field_id": "White/colourless crystalline material", "safe_note": "Use only when deficiency/soil test indicates zinc need."},
]

WEED_IDENTIFICATION: list[dict[str, str]] = [
    {"group": "Grassy weeds", "id": "Narrow leaves, parallel veins, jointed stem", "examples": "Echinochloa, Cynodon, wild grasses", "control": "Timely interculture, stale seedbed, crop-specific herbicide only under local recommendation."},
    {"group": "Broad-leaved weeds", "id": "Wider leaves with net venation", "examples": "Amaranthus, Trianthema, Eclipta", "control": "Early hand weeding/hoeing, mulching and crop rotation."},
    {"group": "Sedges", "id": "Triangular stem and underground tubers/rhizomes", "examples": "Cyperus species", "control": "Repeated removal before seed/tuber spread and water/field management."},
]

SEED_TECHNOLOGY_GUIDES: list[str] = [
    "Use truthful labelled/certified seed from reliable source and check germination percentage before sowing.",
    "Seed rate depends on crop, variety, spacing, germination percentage, seed weight and sowing method.",
    "Seed treatment helps reduce seed-borne disease and early pest attack; use only crop-recommended treatment.",
    "Maintain seed storage in cool, dry, clean and pest-free conditions; moisture is a major enemy of seed quality.",
    "For practical files, record seed source, lot number, germination test, purity, treatment and sowing date.",
]

IRRIGATION_METHOD_GUIDES: list[dict[str, str]] = [
    {"name": "Surface irrigation", "best_for": "Level fields, rice and many field crops", "care": "Avoid over-irrigation and maintain drainage."},
    {"name": "Furrow irrigation", "best_for": "Row crops such as maize, vegetables, sugarcane", "care": "Keep water in furrows, not directly around plant collar for long periods."},
    {"name": "Sprinkler irrigation", "best_for": "Light soils, undulating land and many field crops", "care": "Avoid windy operation and disease-prone wet foliage periods."},
    {"name": "Drip irrigation", "best_for": "Vegetables, fruit crops, plantation crops and water-saving systems", "care": "Filter water, prevent clogging and schedule irrigation by crop stage."},
]

CAREER_EXAM_BANK: list[dict[str, str]] = [
    {"path": "Higher studies", "fit": "Students interested in research, teaching or specialization", "exams": "ICAR AIEEA PG / CUET-PG where applicable, university PG entrance, ICAR-JRF for PG level", "prep": "Strengthen core subject, objective questions, statistics and research basics."},
    {"path": "Banking agriculture field", "fit": "Students interested in rural credit and farmer advisory", "exams": "IBPS AFO / specialist officer routes after eligibility, NABARD-related opportunities", "prep": "Agronomy, soil, horticulture, animal husbandry, economics and current agriculture schemes."},
    {"path": "Government agriculture services", "fit": "Students interested in agriculture officer / extension work", "exams": "State agriculture officer exams, horticulture officer, soil conservation and allied posts depending on notification", "prep": "State crops, schemes, pest/disease, soil conservation and extension."},
    {"path": "Research and academia", "fit": "Students who enjoy experiments, data and scientific writing", "exams": "ICAR-JRF/SRF, ARS/NET where eligible, university PhD entrance", "prep": "Research methodology, statistics, subject depth, scientific writing and literature review."},
    {"path": "Agri-startup / private sector", "fit": "Students interested in business, precision farming, input industry or consulting", "exams": "Campus placements, internships, certifications and entrepreneurship programs", "prep": "Field diagnosis, communication, data tools, product knowledge and farm economics."},
]

DOMAIN_FIELD_CONFIG: dict[str, Mapping[str, Any]] = {
    "Agronomy": {"show": ["crop", "plant_category", "soil", "method", "district", "field_problem"], "pests": ["Stem Borer", "Brown Plant Hopper", "Fall Armyworm", "Aphids", "Weed pressure"], "diseases": ["Blast", "Wilt", "Rust", "Leaf spot", "Nutrient deficiency"]},
    "Soil Science": {"show": ["crop", "soil", "method", "district", "field_problem"], "pests": ["Not primary"], "diseases": ["Nutrient deficiency", "Wilt", "Root rot", "Salinity stress"]},
    "Entomology": {"show": ["crop", "plant_category", "pest", "district", "field_problem"], "pests": list(PEST_LIBRARY.keys()), "diseases": ["Vector-borne disease", "Leaf Curl", "Sooty mould"]},
    "Plant Pathology": {"show": ["crop", "plant_category", "disease", "soil", "district", "field_problem"], "pests": ["Whitefly", "Aphids", "Thrips", "Nematodes"], "diseases": list(DISEASE_LIBRARY.keys())},
    "Horticulture": {"show": ["crop", "plant_category", "pest", "disease", "method", "district"], "pests": ["Fruit Fly", "Fruit Borer", "Mealybug", "Thrips", "Mites"], "diseases": ["Anthracnose", "Powdery Mildew", "Downy Mildew", "Wilt", "Black Rot"]},
    "Genetics & Plant Breeding": {"show": ["crop", "plant_category", "disease", "district"], "pests": ["Target pest for resistance", "Brown Plant Hopper", "Stem Borer", "Whitefly"], "diseases": ["Blast", "Rust", "Wilt", "Leaf Curl", "Bacterial Leaf Blight"]},
    "Seed Science": {"show": ["crop", "plant_category", "disease", "soil", "field_problem"], "pests": ["Storage Grain Pests", "Seedling pests"], "diseases": ["Seed-borne Diseases", "Blast", "Wilt", "Bacterial Leaf Blight"]},
    "Crop Physiology": {"show": ["crop", "plant_category", "soil", "method", "field_problem"], "pests": ["Not primary"], "diseases": ["Drought stress", "Heat stress", "Nutrient deficiency", "Waterlogging stress"]},
    "Agricultural Economics": {"show": ["crop", "plant_category", "method", "district"], "pests": ["Production risk"], "diseases": ["Yield loss risk"]},
    "Extension Education": {"show": ["crop", "district", "field_problem", "method"], "pests": ["Farmer advisory topic"], "diseases": ["Farmer advisory topic"]},
    "Agricultural Engineering": {"show": ["crop", "soil", "method", "district", "field_problem"], "pests": ["Not primary"], "diseases": ["Not primary"]},
    "Remote Sensing & GIS": {"show": ["crop", "plant_category", "disease", "district", "field_problem"], "pests": ["Pest hotspot", "Brown Plant Hopper", "Fall Armyworm", "Whitefly"], "diseases": ["Disease hotspot", "Blast", "Late Blight", "Wilt", "Leaf Curl"]},
    "Animal Husbandry & Fisheries": {"show": ["animal", "district", "field_problem", "method"], "pests": ["Ticks", "Lice", "Poultry mites", "Fish parasites"], "diseases": ["Mastitis", "FMD", "PPR", "Newcastle disease", "Fish fungal infection"]},
    "Agroforestry & Forestry": {"show": ["crop", "plant_category", "soil", "method", "district"], "pests": ["Termites", "Defoliators", "Stem borers"], "diseases": ["Root rot", "Leaf spot", "Wilt"]},
    "Food & Post Harvest": {"show": ["crop", "plant_category", "disease", "method", "field_problem"], "pests": ["Storage Grain Pests", "Fruit Fly", "Rodents"], "diseases": ["Post Harvest Rot", "Anthracnose", "Fungal spoilage"]},
}

STUDENT_DOMAIN_CONFIG: dict[str, dict[str, Any]] = {}
for _area, _topics in STUDENT_AREAS.items():
    _config = dict(DOMAIN_FIELD_CONFIG.get(_area, DOMAIN_FIELD_CONFIG["Agronomy"]))
    _config["topics"] = _topics
    _config["show"] = _config.get("show", [])
    _config["pests"] = _config.get("pests", list(PEST_LIBRARY.keys()))
    _config["diseases"] = _config.get("diseases", list(DISEASE_LIBRARY.keys()))
    STUDENT_DOMAIN_CONFIG[_area] = _config

__all__ = [
    "STUDENT_AREAS",
    "ACADEMIC_LEVELS",
    "STUDY_PURPOSES",
    "STUDY_DEPTHS",
    "PLANT_CATEGORIES",
    "FARMING_METHODS",
    "ANIMAL_LIBRARY",
    "FIELD_PROBLEM_OPTIONS",
    "OUTPUT_FORMATS",
    "SEMESTER_WISE_GUIDE",
    "FERTILIZER_IDENTIFICATION",
    "WEED_IDENTIFICATION",
    "SEED_TECHNOLOGY_GUIDES",
    "IRRIGATION_METHOD_GUIDES",
    "CAREER_EXAM_BANK",
    "DOMAIN_FIELD_CONFIG",
    "STUDENT_DOMAIN_CONFIG",
]
