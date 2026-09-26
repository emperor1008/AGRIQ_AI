"""Student/Research intelligence service (ARC-07).

Generates structured learning material, research plans, question banks,
MCQs, viva content, calculators and career guidance for agriculture
students. All content is deterministic, curriculum-style reference text —
nothing here fabricates research data, citations or exam answers from an
external model.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..domain.catalogs.crops import resolve_crop
from ..domain.catalogs.diseases import DISEASE_LIBRARY
from ..domain.catalogs.education import (
    ANIMAL_LIBRARY,
    CAREER_EXAM_BANK,
    FARMING_METHODS,
    FERTILIZER_IDENTIFICATION,
    IRRIGATION_METHOD_GUIDES,
    PEST_LIBRARY,
    PLANT_CATEGORIES,
    SEMESTER_WISE_GUIDE,
    SEED_TECHNOLOGY_GUIDES,
    STUDENT_AREAS,
    WEED_IDENTIFICATION,
)
from ..domain.catalogs.soils import SOIL_LIBRARY


def library_lookup(library: Mapping[str, Any], selected: str | None, fallback: str | None = None) -> tuple[str, Any]:
    """Fuzzy-resolve a user selection against a catalog dictionary."""
    if not selected:
        selected = fallback
    if selected in library:
        return selected, library[selected]
    selected_lower = str(selected or "").strip().lower()
    for key, value in library.items():
        if key.lower() == selected_lower or selected_lower in key.lower() or key.lower() in selected_lower:
            return key, value
    first_key = fallback if fallback in library else next(iter(library))
    return first_key, library[first_key]


# ---------------------------------------------------------------------------
# Content builders (ported verbatim from the legacy monolith)
# ---------------------------------------------------------------------------

def make_exam_points(area, topic, crop, pest_name, disease_name, academic_level, purpose):
    base = [
        f"Define {topic} in 2-3 simple lines.",
        f"Write importance in {crop['name']} or a locally relevant crop example.",
        "Mention cause/factor, field symptom/observation and crop stage affected.",
        "Draw a small labelled flowchart where possible instead of writing only theory.",
        "End with integrated management, advantage, limitation and safety note.",
    ]
    if "Research" in academic_level or "M.Sc" in academic_level:
        base += [
            "Add hypothesis, variables, sampling method and expected statistical comparison.",
            "Mention source of error, replication and how data will be validated.",
        ]
    if "Viva" in purpose:
        base += ["Prepare one definition, one example, one diagram and one field application for oral answer."]
    if area == "Animal Husbandry & Fisheries":
        base[1] = "Use dairy/poultry/goat/fish example and connect housing, feed, health and economics."
    return base


def make_viva_questions(area, topic, crop, pest_name, disease_name, animal_species):
    questions = [
        f"What is {topic} and why is it important in agriculture?",
        "How will you identify the problem in field conditions?",
        "Which factors increase the severity or spread of the problem?",
        "What is the difference between prevention and control?",
        "Why should integrated management be preferred over a single method?",
    ]
    if area == "Entomology":
        questions += [f"What type of pest is {pest_name}?", "What is ETL and why is it important?"]
    elif area == "Plant Pathology":
        questions += [f"What are the three sides of disease triangle for {disease_name}?", "How do fungal, bacterial and viral symptoms differ?"]
    elif area == "Animal Husbandry & Fisheries":
        questions += [f"What records should be maintained in {animal_species} management?", "Why are sanitation and vaccination important?"]
    elif area == "Soil Science":
        questions += ["Why is soil sampling important?", "How do soil pH and organic carbon affect nutrient availability?"]
    return questions


def make_memory_cards(topic, pest_name, disease_name, soil_type, method):
    return [
        {"front": "Disease triangle", "back": "Host + pathogen + favourable environment are required for disease development."},
        {"front": "ETL", "back": "Economic Threshold Level: pest level at which control action should be considered."},
        {"front": "IPM", "back": "Integrated Pest Management combines cultural, mechanical, biological and need-based chemical control."},
        {"front": str(pest_name), "back": "Remember host, identification mark, damage symptom, life cycle and IPM."},
        {"front": str(disease_name), "back": "Remember causal agent, symptom, favourable condition, disease cycle and IDM."},
        {"front": str(soil_type), "back": "Connect soil texture, fertility, water-holding capacity and crop suitability."},
        {"front": str(method), "back": "Write principle, steps, benefit, limitation and field example."},
        {"front": str(topic), "back": "Use definition → diagram → example → practical use → limitation format."},
    ]


def build_diagrams(area, topic, pest_name, disease_name, animal_species):
    if area == "Entomology":
        main = ["Egg", "Larva / Nymph", "Pupa / Growth", "Adult", "Damage / Spread"]
        decision = ["Scout field", "Identify pest", "Compare ETL", "Use IPM", "Review after 3 days"]
    elif area == "Plant Pathology":
        main = ["Host", "Pathogen", "Environment", "Symptoms", "IDM Decision"]
        decision = ["Observe symptom", "Check weather", "Confirm disease", "Remove source", "Need-based control"]
    elif area == "Animal Husbandry & Fisheries":
        main = ["Breed / Species", "Housing", "Feed & Water", "Health Record", "Production Output"]
        decision = ["Observe animal", "Check feed", "Check hygiene", "Record symptoms", "Call expert if severe"]
    elif area == "Remote Sensing & GIS":
        main = ["Satellite/Drone Data", "Pre-processing", "Index/Layer", "Hotspot Map", "Field Validation"]
        decision = ["Select area", "Collect coordinates", "Create layer", "Compare field data", "Interpret result"]
    else:
        main = ["Concept", "Field Observation", "Factor", "Decision", "Result"]
        decision = ["Select topic", "Collect data", "Analyse", "Interpret", "Write conclusion"]
    return {"main": main, "decision": decision, "research": ["Title", "Objectives", "Variables", "Sampling", "Analysis", "Conclusion"]}


def build_student_research_plan(area, topic, crop, pest_name, disease_name, animal_species, district, academic_level):
    subject = animal_species if area == "Animal Husbandry & Fisheries" else crop["name"]
    title = f"Study on {topic} in {subject} under {district} conditions"
    if area == "Entomology":
        title = f"Field incidence and management study of {pest_name} in {crop['name']}"
    elif area == "Plant Pathology":
        title = f"Symptom diagnosis and disease risk study of {disease_name} in {crop['name']}"
    elif area == "Soil Science":
        title = f"Soil health assessment and nutrient management study for {crop['name']}"
    elif area == "Animal Husbandry & Fisheries":
        title = f"Management and productivity assessment of {animal_species} units in {district}"

    return {
        "title": title,
        "objectives": [
            f"To study the basic concept of {topic} in a practical field situation.",
            f"To identify important factors affecting {subject} performance or health.",
            "To prepare a simple management/recommendation plan based on observation and data.",
        ],
        "hypothesis": f"Better field diagnosis and integrated management can improve {subject} performance and reduce loss.",
        "variables": [
            "Independent variables: crop/variety, soil/weather/management, location and treatment practice.",
            "Dependent variables: incidence, severity, yield/production, cost, benefit or learning score.",
            "Control variables: crop stage, sampling size, observation date and measurement method.",
        ],
        "methodology": [
            "Select representative field/farm units and record location, date and management history.",
            "Use random or systematic sampling instead of observing only one plant/animal/pond corner.",
            "Record symptoms, severity score, pest/disease count or production data in a table.",
            "Compare results with weather, soil, management and academic theory.",
            "Write conclusion with recommendation, limitation and future scope.",
        ],
        "analysis_tools": ["Percentage incidence", "Severity score", "Mean comparison", "Benefit-cost ratio", "Graph/chart", "Photographic evidence", "GIS map if location data is available"],
    }


def build_semester_materials(area, topic, crop, pest_name, disease_name, academic_level, output_format):
    """Detailed semester-wise materials, not only overview text."""
    subjects = SEMESTER_WISE_GUIDE.get(academic_level, SEMESTER_WISE_GUIDE["B.Sc Agriculture Semester 3-4"])
    subject_focus = f"{area}: {topic}"
    crop_name = crop.get("name", "selected crop")
    notes = [
        {
            "unit": "Unit 1",
            "title": f"Foundation of {topic}",
            "details": (
                f"Define {topic}, write its scope in agriculture, and explain why it matters for crop production, "
                f"soil health, plant protection, research and farmer decision-making. Add one example from {crop_name}."
            ),
        },
        {
            "unit": "Unit 2",
            "title": f"Crop-linked understanding: {crop_name}",
            "details": (
                f"Connect the topic with {crop_name}: season ({crop.get('season','')}), suitable soil ({crop.get('soil','')}), "
                f"major pests ({crop.get('pests','')}) and major diseases ({crop.get('diseases','')}). Explain how growth stage changes management priority."
            ),
        },
        {
            "unit": "Unit 3",
            "title": "Field diagnosis and observation method",
            "details": (
                "Write a field observation format: date, district/location, crop stage, symptom, affected plant %, severity score, "
                "weather condition, soil/water status, photo evidence and farmer practice. This makes the answer research-ready."
            ),
        },
        {
            "unit": "Unit 4",
            "title": "Management and recommendation framework",
            "details": (
                "Use an integrated approach: prevention, cultural practice, mechanical removal, biological/natural support, "
                "need-based chemical escalation, safety precautions and post-treatment monitoring. Avoid unsupported dosage claims."
            ),
        },
        {
            "unit": "Unit 5",
            "title": "Research, assignment and viva connection",
            "details": (
                "Convert the topic into a mini research project by adding objectives, variables, sampling method, data table, "
                "statistical analysis, conclusion, limitations and future scope. For viva, answer in definition → example → field use format."
            ),
        },
    ]
    return {
        "subject_focus": subject_focus,
        "semester_subjects": subjects,
        "notes": notes,
        "recommended_output": output_format,
        "study_hint": (
            "Use the dropdown cards one by one: start from notes, then question bank, then research method, "
            "then basic agriculture knowledge, calculators, career and viva."
        ),
    }


def build_question_bank(area, topic, crop, pest_name, disease_name, academic_level):
    important = [
        f"Define {topic} and explain its importance in agriculture with a field example.",
        f"Explain {topic} with reference to {crop['name']} cultivation and crop stage.",
        f"Describe symptoms, favourable conditions, disease cycle and integrated management of {disease_name}.",
        f"Write identification marks, damage symptoms, life cycle and IPM of {pest_name}.",
        "Differentiate between prevention, control, eradication and integrated management.",
        "Explain the role of soil, water, weather and nutrition in crop health.",
        "Write a field diagnosis format for the selected crop problem.",
        "Explain how data should be collected for a mini research project in agriculture.",
        "Write limitations and safety precautions while giving farmer recommendations.",
        "Explain how climate-smart agriculture can reduce crop risk.",
    ]
    assignment = [
        f"Prepare a 1200-word assignment on {topic} with introduction, objectives, importance, field example, management and conclusion.",
        f"Create a pest/disease profile sheet for {pest_name} and {disease_name} in {crop['name']}.",
        "Prepare a practical observation table with date, crop stage, symptom, severity, photo evidence and recommendation.",
        "Write a short review on integrated management and explain why single-method control is not enough.",
        "Design a farmer advisory leaflet in simple language for the selected field problem.",
        "Prepare a research proposal with title, objectives, hypothesis, variables, sampling and expected outcome.",
    ]
    mcqs = [
        {"q": f"Which is the first step before recommending treatment for {disease_name}?", "options": ["Confirm symptoms", "Spray immediately", "Ignore weather", "Apply random mixture"], "answer": "A. Confirm symptoms", "explain": "Diagnosis should come before treatment because wrong treatment wastes money and can damage the crop."},
        {"q": "ETL is mostly used in which area?", "options": ["Pest management", "Seed storage only", "Soil texture only", "Marketing only"], "answer": "A. Pest management", "explain": "Economic Threshold Level helps decide when pest control is economically justified."},
        {"q": "Which factor increases many fungal diseases?", "options": ["High humidity and leaf wetness", "Dry seed only", "Clean field drainage", "Balanced spacing"], "answer": "A. High humidity and leaf wetness", "explain": "Moist leaf surfaces support spore germination and disease spread."},
        {"q": "Which record is most useful in field research?", "options": ["Date, location and observation", "Only crop name", "Only farmer name", "Only photo without note"], "answer": "A. Date, location and observation", "explain": "A research record must be traceable, repeatable and comparable."},
        {"q": "Why is excess nitrogen risky?", "options": ["It may increase soft growth and pest/disease pressure", "It removes all pests", "It stops all disease", "It replaces irrigation"], "answer": "A. It may increase soft growth and pest/disease pressure", "explain": "Balanced nutrition is safer than excess single nutrient."},
        {"q": f"Which approach is best for managing {pest_name}?", "options": ["Integrated Pest Management", "Single repeated chemical only", "No field scouting", "Ignoring crop stage"], "answer": "A. Integrated Pest Management", "explain": "IPM combines monitoring, prevention, biological/natural methods and need-based chemical use."},
        {"q": "Which sample method is usually better than observing only one plant?", "options": ["Random or systematic sampling", "Only gate-side observation", "Only tallest plant observation", "Only photo editing"], "answer": "A. Random or systematic sampling", "explain": "Representative sampling reduces bias in research and field diagnosis."},
        {"q": "Which statement is safest for fertilizer recommendation?", "options": ["Use soil-test and local recommendation", "Apply maximum urea always", "Guess the dose by leaf colour only", "Use the same dose for every crop"], "answer": "A. Use soil-test and local recommendation", "explain": "Exact fertilizer dose needs soil test, crop requirement and local package of practices."},
    ]
    labels = ["A", "B", "C", "D"]
    for mcq in mcqs:
        mcq["option_rows"] = [{"label": labels[i], "text": opt} for i, opt in enumerate(mcq["options"][:4])]
    return {"important": important, "assignment": assignment, "mcqs": mcqs}


def build_research_methodology_guides(area, topic, crop, district):
    return {
        "methodology_steps": [
            f"Problem selection: Write a narrow title around {topic}, {crop['name']} and {district}. Avoid very broad titles like 'study of agriculture'.",
            "Review of literature: Read textbooks, extension bulletins, research papers and official package-of-practices notes. Keep references in one notebook.",
            "Objectives: Write 2-4 measurable objectives. Each objective should be answerable by your collected data.",
            "Hypothesis: Write a simple expected relationship, for example weather/management may influence incidence, severity, yield or cost.",
            "Variables: Decide independent variables such as variety, soil, weather, treatment or management, and dependent variables such as incidence, severity, yield or benefit-cost ratio.",
            "Sampling method: Use random, systematic, stratified or purposive sampling depending on field situation. Mention sample size clearly.",
            "Data sheet: Prepare columns for date, location, crop stage, symptom, pest count, severity score, soil/water condition, weather and photo evidence.",
            "Field observation: Observe multiple spots instead of one corner. Take photos but also record numbers.",
            "Analysis: Start with percentage, mean, chart and comparison. Use t-test, ANOVA, correlation or regression only when data type and sample size support it.",
            "Conclusion: Link result with objective. Add recommendation, limitation and future scope instead of only repeating theory.",
        ],
        "statistical_analysis": [
            "Percentage incidence = affected plants ÷ total observed plants × 100.",
            "Disease severity index = sum of all rating scores ÷ maximum possible score × 100.",
            "Mean summarizes average observation; standard deviation shows variation among observations.",
            "t-test is used when comparing two groups, such as treated vs untreated plot.",
            "ANOVA is used when comparing more than two treatments or varieties.",
            "Correlation checks relationship between two variables such as humidity and disease severity; it does not prove direct cause alone.",
            "Regression estimates how one or more factors influence yield/risk, but it requires enough clean observations.",
            "Chi-square can be used for categorical survey data such as adoption yes/no across groups.",
            "Use bar chart for treatment comparison, line chart for time trend, scatter plot for relationship and map for location-wise risk.",
        ],
        "plagiarism_guidance": [
            "Do not copy full paragraphs from books, PDFs or websites.",
            "Read the source, close it, then write the idea in your own words.",
            "Cite sources in bibliography with author/organization, year, title and link/book details where available.",
            "Use quotation marks only for short exact definitions, not for whole assignment sections.",
            "Add original field data, tables, photos and interpretation to make the work genuinely yours.",
            "Use your institution-approved plagiarism checker if available; do not trust random fake percentage tools.",
            "Keep AI-generated text as a draft only. Verify facts, add references and write your own observations before submission.",
        ],
        "report_format": [
            "Title page", "Abstract", "Introduction", "Review of literature", "Objectives", "Materials and methods",
            "Results", "Discussion", "Conclusion", "Recommendations", "References", "Appendix / data sheet"
        ],
        "ethics": "Use safe field practices, get permission before surveying farms, do not publish farmer personal details, and verify chemical recommendations with official/local advisory.",
    }


def build_basic_knowledge(area, crop, pest_name, pest, disease_name, disease, soil_type, soil, method):
    return {
        "crop_production": [
            f"Crop: {crop['name']} ({crop.get('scientific','')})",
            f"Season: {crop['season']}",
            f"Suitable soil: {crop['soil']}",
            f"Management focus: {crop['management']}",
            "Write production guide as: land preparation → seed/seedling → spacing → nutrient → irrigation → weed → pest/disease → harvest.",
        ],
        "soil_science": [
            f"Selected soil: {soil_type}. {soil['features']}",
            f"Common issue: {soil['problems']}",
            f"Management: {soil['management']}",
            "For real fertilizer recommendation, soil test is required. The app gives calculator logic, not final official dose.",
        ],
        "plant_disease_identification": [
            f"Disease: {disease_name}",
            f"Agent: {disease.get('agent','')}",
            f"Symptom: {disease.get('symptom','')}",
            f"Favourable condition: {disease.get('favour','')}",
            f"Disease cycle: {disease.get('cycle','')}",
            f"IDM: {disease.get('management','')}",
        ],
        "pest_life_cycle": [
            f"Pest: {pest_name}",
            f"Type: {pest.get('type','')}",
            f"Host: {pest.get('hosts','')}",
            f"Identification: {pest.get('id','')}",
            f"Damage: {pest.get('damage','')}",
            f"Life cycle: {pest.get('life','')}",
            f"IPM: {pest.get('management','')}",
        ],
        "fertilizer_identification": FERTILIZER_IDENTIFICATION,
        "weed_identification": WEED_IDENTIFICATION,
        "seed_technology": SEED_TECHNOLOGY_GUIDES,
        "irrigation_methods": IRRIGATION_METHOD_GUIDES,
        "method_note": method,
    }


def build_calculator_guides(crop):
    return {
        "fertilizer": {
            "formula": "Required fertilizer kg = nutrient requirement kg ÷ nutrient fraction in fertilizer",
            "example": "For 46% N urea: urea kg = required N kg ÷ 0.46.",
            "note": "Use soil-test and local package-of-practices values. This calculator is educational, not a legal prescription.",
        },
        "seed_rate": {
            "formula": "Seed rate kg/ha = recommended seed rate × 100 ÷ germination percentage",
            "example": "If recommendation is 40 kg/ha and germination is 80%, adjusted seed = 50 kg/ha.",
            "note": f"Adjust further for {crop['name']} variety, spacing and sowing method.",
        },
        "unit_converter": {
            "area": "1 hectare = 2.471 acre; 1 acre = 0.4047 hectare",
            "weight": "1 quintal = 100 kg; 1 tonne = 1000 kg",
            "water": "1 mm rain over 1 hectare ≈ 10,000 litres of water",
        },
    }


def build_career_guidance(area, academic_level):
    focus = "Research and higher studies" if "M.Sc" in academic_level or "Research" in academic_level else "Foundation + exam readiness"
    suggested = CAREER_EXAM_BANK
    if area in {"Entomology", "Plant Pathology", "Soil Science", "Genetics & Plant Breeding"}:
        focus = "Subject specialization, research, seed/input sector and government services"
    elif area in {"Agricultural Economics", "Extension Education"}:
        focus = "Agri banking, rural development, extension, policy and entrepreneurship"
    elif area in {"Remote Sensing & GIS", "Agricultural Engineering"}:
        focus = "Agri-tech, GIS, precision farming, irrigation and data-driven agriculture roles"
    return {"focus": focus, "paths": suggested, "disclaimer": "Always verify eligibility, age, degree requirements and latest notification before applying."}


def build_student_result_cards(area, topic, crop, pest_name, pest, disease_name, disease, soil_type, soil, method, animal_species, animal, field_problem):
    if area == "Animal Husbandry & Fisheries":
        definition = f"{topic} means studying practical management of {animal_species} including breed/species selection, housing, feeding, sanitation, health care, production records and economics."
        easy_answer = (
            f"In simple words, {topic} helps a student understand how to keep {animal_species} healthy and productive. "
            "For exams, write the definition, important management points, records to maintain, common problems and prevention methods. "
            "For research, compare one management factor such as feed, housing hygiene, temperature, stocking density or vaccination with production output."
        )
        key_terms = ["Breed/species", "Housing", "Balanced ration", "Vaccination", "Sanitation", "Production record", "Mortality", "Benefit-cost ratio"]
    else:
        definition = f"{topic} is the study of how crop, soil, pest, disease, climate and management factors influence agricultural production and decision-making."
        easy_answer = (
            f"For {crop['name']}, understand the crop requirement first: season, soil, growth stage, common pests and common diseases. "
            f"Then connect the topic with a real field example such as {pest_name}, {disease_name}, {soil_type} soil or {method}. "
            "This gives a complete exam-ready and research-ready answer instead of only memorising theory."
        )
        key_terms = ["Crop stage", "Pest incidence", "Disease severity", "Soil pH", "NPK", "ETL", "IPM/IDM", "Yield loss", "Sampling", "Recommendation"]

    return {
        "definition": definition,
        "easy_answer": easy_answer,
        "key_terms": key_terms,
        "field_problem_note": f"Selected field/research problem: {field_problem}. Connect it with symptoms, cause, diagnosis and management.",
    }


def build_student_dropdown_sections(result):
    """Create ordered dropdown cards for student/research mode after Analyze."""
    sections = []
    sections.append({
        "anchor": "studyWorkspace",
        "title": "📘 1. Detailed Concept Explanation",
        "badge": result["area"],
        "paragraphs": [result["definition"], result["easy_answer"], result["field_problem_note"]],
        "items": [f"Key term: {term}" for term in result.get("key_terms", [])],
    })
    sections.append({
        "anchor": "materialsHub",
        "title": "📚 2. Semester-Wise Notes & Materials",
        "badge": result["academic_level"],
        "paragraphs": [result["semester_materials"].get("study_hint", "Use these notes for exam and assignment preparation.")],
        "rows": [{"left": note["unit"] + " — " + note["title"], "right": note["details"]} for note in result["semester_materials"].get("notes", [])],
        "items": ["Subject focus: " + result["semester_materials"].get("subject_focus", "")] + ["Semester subject: " + s for s in result["semester_materials"].get("semester_subjects", [])],
    })
    sections.append({
        "anchor": "questionBankHub",
        "title": "📝 3. Important + Assignment Questions",
        "badge": result["purpose"],
        "paragraphs": ["Use these for written answers, assignments, class tests and internal exams."],
        "items": ["Important: " + q for q in result["question_bank"].get("important", [])] + ["Assignment: " + q for q in result["question_bank"].get("assignment", [])],
    })
    sections.append({
        "anchor": "mcqHub",
        "title": "✅ 4. MCQ Practice with 4 Options",
        "badge": "A/B/C/D + answer",
        "paragraphs": ["Each MCQ has exactly four options, the correct answer and a short explanation."],
        "mcqs": result["question_bank"].get("mcqs", []),
    })
    if result.get("animal_mode"):
        sections.append({
            "anchor": "basicKnowledge",
            "title": "🐄 5. Animal Husbandry / Fisheries Knowledge Card",
            "badge": result.get("animal_species", "Animal / Fishery"),
            "paragraphs": [
                "Focus: " + result["animal"].get("focus", ""),
                "Records: " + result["animal"].get("records", ""),
                "Exam point: " + result["animal"].get("exam", ""),
                "Research idea: " + result["animal"].get("research", ""),
            ],
            "rows": result.get("crop_matrix", []),
        })
    else:
        sections.append({
            "anchor": "basicKnowledge",
            "title": "🌿 5. Basic Agriculture Knowledge Hub",
            "badge": result["crop"].get("name", "Crop"),
            "paragraphs": ["Crop production, soil science, disease identification, pest life cycle, fertilizer, weed, seed and irrigation information are organized below."],
            "rows": [
                {"left": "Crop academic profile", "right": f"{result['crop']['name']} / {result['crop'].get('odia','')} • {result['crop'].get('scientific','')} • {result['crop'].get('season','')} • Soil: {result['crop'].get('soil','')}"},
                {"left": "Common pests", "right": result['crop'].get('pests', '')},
                {"left": "Common diseases", "right": result['crop'].get('diseases', '')},
                {"left": "Selected soil", "right": f"{result['soil_type']}: {result['soil'].get('features','')} Problem: {result['soil'].get('problems','')} Management: {result['soil'].get('management','')}"},
                {"left": "Selected farming method", "right": result.get('method_note', '')},
                {"left": "Selected problem", "right": result.get('field_problem', '')},
            ],
            "items": result["basic_knowledge"].get("crop_production", []) + result["basic_knowledge"].get("soil_science", []),
        })
        sections.append({
            "anchor": "plantProtectionHub",
            "title": "🐛 6. Pest + Disease Identification",
            "badge": result.get("pest_name", "Pest") + " / " + result.get("disease_name", "Disease"),
            "rows": [
                {"left": "Pest type", "right": result["pest"].get("type", "")},
                {"left": "Pest identification", "right": result["pest"].get("id", "")},
                {"left": "Pest damage", "right": result["pest"].get("damage", "")},
                {"left": "Pest life cycle", "right": result["pest"].get("life", "")},
                {"left": "Pest IPM", "right": result["pest"].get("management", "")},
                {"left": "Disease agent", "right": result["disease"].get("agent", "")},
                {"left": "Disease symptoms", "right": result["disease"].get("symptom", "")},
                {"left": "Favourable condition", "right": result["disease"].get("favour", "")},
                {"left": "Disease cycle", "right": result["disease"].get("cycle", "")},
                {"left": "IDM", "right": result["disease"].get("management", "")},
            ],
        })
    sections.append({
        "anchor": "researchToolkit",
        "title": "🔬 7. Research Methodology + Statistics",
        "badge": "Thesis / project ready",
        "paragraphs": ["Research title: " + result["research"].get("title", ""), "Hypothesis: " + result["research"].get("hypothesis", "")],
        "items": ["Objective: " + x for x in result["research"].get("objectives", [])] + ["Method: " + x for x in result["research_guides"].get("methodology_steps", [])] + ["Statistics: " + x for x in result["research_guides"].get("statistical_analysis", [])],
    })
    sections.append({
        "anchor": "plagiarismHub",
        "title": "🧾 8. Plagiarism-Safe Writing + Report Format",
        "badge": "Research writing",
        "paragraphs": [result["research_guides"].get("ethics", "")],
        "items": ["Plagiarism guidance: " + x for x in result["research_guides"].get("plagiarism_guidance", [])] + ["Report section: " + x for x in result["research_guides"].get("report_format", [])],
    })
    sections.append({
        "anchor": "calculatorHub",
        "title": "🧮 9. Useful Calculators",
        "badge": "Fertilizer / seed / unit",
        "paragraphs": [
            "Fertilizer: " + result["calculator_guides"]["fertilizer"]["formula"],
            "Seed rate: " + result["calculator_guides"]["seed_rate"]["formula"],
            "Unit converter: " + result["calculator_guides"]["unit_converter"]["area"],
        ],
        "calculator": True,
    })
    sections.append({
        "anchor": "careerHub",
        "title": "🎯 10. Career & Exam Direction",
        "badge": "Future plan",
        "paragraphs": [result["career_guidance"].get("focus", ""), result["career_guidance"].get("disclaimer", "")],
        "career_paths": result["career_guidance"].get("paths", []),
    })
    sections.append({
        "anchor": "examPrep",
        "title": "🎤 11. Exam Answer + Viva + Memory Cards",
        "badge": "Revision",
        "items": ["Exam point: " + x for x in result.get("exam_points", [])] + ["Viva: " + x for x in result.get("viva", [])],
        "memory_cards": result.get("memory_cards", []),
    })
    sections.append({
        "anchor": "knowledgeAtlas",
        "title": "🗂️ 12. Knowledge Atlas",
        "badge": "Reference bank",
        "rows": [{"left": category, "right": ", ".join(items)} for category, items in result.get("tree_fruit_vegetable_bank", {}).items()],
        "items": (
            ["Pest: " + p["name"] + " — " + p["hosts"] + " — " + p["damage"] for p in result.get("all_pests", [])[:12]]
            + ["Disease: " + d["name"] + " — " + d["hosts"] + " — " + d["symptom"] for d in result.get("all_diseases", [])[:12]]
        ),
    })
    return sections


def student_result(form: Mapping[str, Any]) -> dict[str, Any]:
    """Build the complete Student/Research workspace payload from form input."""
    area = form.get("learning_area", "Plant Protection") or "Plant Protection"
    if area not in STUDENT_AREAS:
        area = "Agronomy"
    academic_level = form.get("academic_level", "B.Sc Agriculture Semester 3-4") or "B.Sc Agriculture Semester 3-4"
    purpose = form.get("study_purpose", "Exam Preparation") or "Exam Preparation"
    topic = form.get("topic", STUDENT_AREAS[area][0]) or STUDENT_AREAS[area][0]
    crop_name = form.get("crop", "Rice") or "Rice"
    crop, crop_key = resolve_crop(crop_name)
    plant_category = form.get("plant_category", "Cereals") or "Cereals"
    pest_name, pest = library_lookup(PEST_LIBRARY, form.get("pest_focus"), "Brown Plant Hopper")
    disease_name, disease = library_lookup(DISEASE_LIBRARY, form.get("disease_focus"), "Blast")
    soil_type, soil = library_lookup(SOIL_LIBRARY, form.get("soil_type"), "Alluvial soil")
    method = form.get("farming_method", "Integrated farming system") or "Integrated farming system"
    method_note = FARMING_METHODS.get(method, FARMING_METHODS["Integrated farming system"])
    district = form.get("district", "Cuttack") or "Cuttack"
    field_problem = form.get("field_problem", "Leaf spots") or "Leaf spots"
    animal_species, animal = library_lookup(ANIMAL_LIBRARY, form.get("animal_species"), "Dairy cattle")
    output_format = form.get("output_format", "Study Notes") or "Study Notes"
    study_depth = form.get("study_depth", "Exam-Oriented") or "Exam-Oriented"
    prompt = (form.get("student_prompt") or "").strip()
    animal_mode = area == "Animal Husbandry & Fisheries"

    cards = build_student_result_cards(area, topic, crop, pest_name, pest, disease_name, disease, soil_type, soil, method, animal_species, animal, field_problem)
    diagrams = build_diagrams(area, topic, pest_name, disease_name, animal_species)
    research = build_student_research_plan(area, topic, crop, pest_name, disease_name, animal_species, district, academic_level)
    semester_materials = build_semester_materials(area, topic, crop, pest_name, disease_name, academic_level, output_format)
    question_bank = build_question_bank(area, topic, crop, pest_name, disease_name, academic_level)
    research_guides = build_research_methodology_guides(area, topic, crop, district)
    basic_knowledge = build_basic_knowledge(area, crop, pest_name, pest, disease_name, disease, soil_type, soil, method)
    calculator_guides = build_calculator_guides(crop)
    career_guidance = build_career_guidance(area, academic_level)

    study_path = [
        "Read definition and key terms",
        "Understand diagram / lifecycle / concept flow",
        "Connect with selected crop or animal example",
        "Write field observation and management answer",
        "Revise viva questions and memory cards",
    ]
    if "Research" in purpose or "Research" in academic_level:
        study_path = ["Choose research problem", "Set objectives", "Select variables", "Collect field data", "Analyse and conclude"]

    practical_record = [
        {"heading": "Aim", "value": f"To study {topic} with practical reference to {animal_species if animal_mode else crop['name']}."},
        {"heading": "Materials", "value": "Notebook, field photo, sample/observation sheet, measuring scale, location and date record."},
        {"heading": "Observation", "value": f"Record {field_problem}, stage, severity/count, weather/soil condition and management practice."},
        {"heading": "Result", "value": "Write diagnosis, reason, recommendation and safety/limitation note."},
    ]

    field_sheet = [
        "Date", "District/Location", "Crop/Animal", "Stage/Age", "Soil/Housing", "Symptom/Problem", "Pest/Disease count", "Severity score", "Photo evidence", "Recommendation"
    ]
    if animal_mode:
        field_sheet = ["Date", "Species", "Age/Breed", "Housing", "Feed", "Water", "Symptoms", "Vaccination", "Production", "Recommendation"]

    crop_matrix = [
        {"factor": "Crop / Host", "detail": animal_species if animal_mode else f"{crop['name']} ({crop.get('scientific','')})"},
        {"factor": "Important issue", "detail": field_problem},
        {"factor": "Pest / Vector", "detail": pest_name},
        {"factor": "Disease / Disorder", "detail": disease_name},
        {"factor": "Soil / Housing", "detail": "Clean, ventilated housing" if animal_mode else soil_type},
        {"factor": "Method", "detail": method},
        {"factor": "Study purpose", "detail": purpose},
    ]

    all_pests = [{"name": k, "type": v["type"], "hosts": v["hosts"], "damage": v["damage"]} for k, v in PEST_LIBRARY.items()]
    all_diseases = [{"name": k, "agent": v["agent"], "hosts": v["hosts"], "symptom": v["symptom"]} for k, v in DISEASE_LIBRARY.items()]

    result: dict[str, Any] = {
        "area": area,
        "topic": topic,
        "academic_level": academic_level,
        "purpose": purpose,
        "crop": crop,
        "crop_key": crop_key,
        "plant_category": plant_category,
        "pest_name": pest_name,
        "pest": pest,
        "disease_name": disease_name,
        "disease": disease,
        "soil_type": soil_type,
        "soil": soil,
        "method": method,
        "method_note": method_note,
        "district": district,
        "field_problem": field_problem,
        "animal_mode": animal_mode,
        "animal_species": animal_species,
        "animal": animal,
        "output_format": output_format,
        "study_depth": study_depth,
        "student_prompt": prompt,
        "definition": cards["definition"],
        "easy_answer": cards["easy_answer"],
        "key_terms": cards["key_terms"],
        "field_problem_note": cards["field_problem_note"],
        "diagram": diagrams["main"],
        "decision_flow": diagrams["decision"],
        "research_flow": diagrams["research"],
        "study_path": study_path,
        "exam_points": make_exam_points(area, topic, crop, pest_name, disease_name, academic_level, purpose),
        "viva": make_viva_questions(area, topic, crop, pest_name, disease_name, animal_species),
        "memory_cards": make_memory_cards(topic, pest_name, disease_name, soil_type, method),
        "research": research,
        "practical_record": practical_record,
        "field_sheet": field_sheet,
        "crop_matrix": crop_matrix,
        "all_pests": all_pests,
        "all_diseases": all_diseases,
        "domain_topics": STUDENT_AREAS.get(area, []),
        "tree_fruit_vegetable_bank": PLANT_CATEGORIES,
        "semester_materials": semester_materials,
        "question_bank": question_bank,
        "research_guides": research_guides,
        "basic_knowledge": basic_knowledge,
        "calculator_guides": calculator_guides,
        "career_guidance": career_guidance,
    }
    result["dropdown_sections"] = build_student_dropdown_sections(result)
    return result


__all__ = [
    "library_lookup",
    "student_result",
    "make_exam_points",
    "make_viva_questions",
    "make_memory_cards",
    "build_diagrams",
    "build_question_bank",
    "build_career_guidance",
]
