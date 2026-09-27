# AGRIQ AI — Farming Techniques & Agricultural Knowledge Architecture

Phase 7.2 adds **Farming Techniques**: one canonical, source-verified agricultural
knowledge base, presented through **Farmer Mode** and **Student Mode**, readable in
**English (default)**, **Odia** and **Hindi**.

It is an addition. Nothing existing was replaced: the knowledge feature reuses the
existing layered architecture (models → repositories → services → blueprints →
templates/JS), the existing design system (`tokens.css` variables, `.glass`,
`.data-panel`, `.pill`, `.link-button`, `.dropdown-card`, `.side-rail`, `.topbar`),
the existing `knowledge_sources` provenance table from Phase 2, and the existing
`get_current_user()` authorization dependency from Phase 7.1.

---

## 1. Canonical knowledge, two presentations

```
              Verified agricultural knowledge  (one set of tables)
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
      Farmer Mode projection        Student Mode projection
      (decision support)            (educational)
                │                           │
                └─────────────┬─────────────┘
                              ▼
                   Same facts, same sources,
                   same evidence classification
```

There is **no second database**. `services/farming_knowledge.py` reads one set of
records and renders two field orderings:

| Mode | Section order |
| --- | --- |
| Farmer (default) | Summary → When it is useful → Method / practice → Benefits → Limitations → Safety → Modern relevance |
| Student | Summary → Principle → Background / historical context → Method → Benefits → Limitations → Applications → Modern relevance + key terms, comparison notes, study summary |

Switching mode is a `mode=farmer|student` parameter. The `mode` never changes which
records exist or which source backs them.

Farmer pages carry `farmer.not_a_recommendation`; student pages carry
`student.not_a_recommendation`. Neither presentation turns a documented practice into
advice for a specific field.

---

## 2. Categories

Stored as `farming_techniques.category` (`CATEGORY_ORDER` in
`models/farming_knowledge.py`):

| Code | UI label key | Content |
| --- | --- | --- |
| `ancient` | `knowledge.category_label_ancient` | Historically documented practices |
| `traditional` | `knowledge.category_label_traditional` | Documented traditional / indigenous practices |
| `modern` | `knowledge.category_label_modern` | Documented modern technologies and practices |
| `organic_biological` | `knowledge.category_label_organic_biological` | Organic, botanical and biological pest management |
| `modern_pesticide` | `knowledge.category_label_modern_pesticide` | Regulatory pesticide information |

Modern pesticide records are deliberately **kept out of the general practice
listing**: `list_entries()` routes `category=modern_pesticide` to a separate table and
a separate safety frame, so a pesticide record can never be read in a stream of
cultivation advice.

Category counts are per-language labels resolved through the i18n catalog. No phase
or development terminology is exposed in the UI.

---

## 3. Provenance model

Every record points at a `knowledge_sources` row (the Phase 2 table, extended in
Phase 7.2 with `source_key`, `document_type`, `date_note`, `licence_note`,
`region_scope`, `review_status`, `reviewed_by`, `reviewed_at`).

Minimum provenance stored per source:

```
source_name (title)      source_organisation     source_url
source_type              document_type           publication_title
publication_date         date_note               accessed_at
licence_note             region                  review_status
reviewed_by              reviewed_at             last_verified_at
```

`source_type` values: `GOVERNMENT`, `RESEARCH_INSTITUTE`, `AGRICULTURAL_UNIVERSITY`,
`EXTENSION_SERVICE`, `INTERNATIONAL_ORGANIZATION`, `PEER_REVIEWED_RESEARCH`,
`OFFICIAL_PRODUCT_LABEL`, `HISTORICAL_REFERENCE`.

Two rules make the model honest:

* **No AI output can become a source.** Sources are created only by the import CLI
  from a dataset file, and only become readable after a named reviewer approves them.
* **A date that the document does not state is `null`, never guessed.** The dataset
  carries `date_note` explaining why a date is absent.

---

## 4. Evidence classification

`models/farming_knowledge.py`:

```
HISTORICAL                    EVIDENCE_LIMITED
TRADITIONAL                   EXTENSION_RECOMMENDATION
RESEARCH_SUPPORTED            REGULATORY
OFFICIAL_PRODUCT_INFORMATION
```

`KnowledgeEvidence` rows attach individual claims to a level and to a
`source_section`, so the detail page can show *which* claim is supported at *which*
strength — not one blanket badge for a whole page.

Ancient and traditional records are labelled `HISTORICAL` / `TRADITIONAL` and the
detail view prints `student.evidence_note` (a "historical practice is not a modern
validated recommendation" notice) whenever `detail.historical` is true. AGRIQ never
implies that an old practice is scientifically proven.

---

## 5. Review gate (the reason nothing unverified is visible)

Every knowledge record has its own `review_status`
(`PENDING_REVIEW` → `VERIFIED` / `REJECTED` → `EXPIRED`), and every read is gated
twice:

1. the record's `review_status == VERIFIED`, **and**
2. its `knowledge_sources.review_status == approved`.

That is the same gate the Phase 2 retriever applies, so the copilot cannot ground on
anything a human has not approved. Pending records are counted and surfaced as
`knowledge.awaiting_review` ("N entries awaiting agricultural review") instead of
being served, and `INSUFFICIENT_REAL_DATA` is returned when filters match nothing.

Ingestion and approval are CLI-only — there is no HTTP route that can insert or
approve knowledge:

```
python -m agriq.cli.import_farming_knowledge --dataset ../../data/farming_knowledge/dataset.json
python -m agriq.cli.review_knowledge --list
python -m agriq.cli.review_knowledge --approve technique biomass-mulching --reviewer "Dr A, OUAT"
python -m agriq.cli.review_knowledge --translation technique biomass-mulching \
    --language hi --field overview --text "..." --reviewed-by "Dr A"
```

Approving a record approves its provenance row and mirrors the reviewed text into
`knowledge_chunks` for retrieval.

---

## 6. Safety: preparation and application data

Two independent, explicitly-named states travel with every record:

```
PREPARATION_DATA_UNAVAILABLE   no credible source documents how to prepare it
APPLICATION_DATA_UNVERIFIED    no current authoritative source states how much/how often
DOCUMENTED / VERIFIED          a cited source does state it
```

Rules enforced in the model, the dataset validator and the UI:

* Preparation text is stored only when a cited authority documents it. Preparation
  is **never** estimated, extrapolated or transferred between records.
* Application/dose data is stored only from a current authoritative source
  (in practice: the official DPPQS "Major Uses of Pesticides" documents). A dose is
  never inferred from another formulation, another crop or another active ingredient.
* Modern pesticide entries carry `pesticide.label_notice` ("follow the approved
  product label and local authority guidance") and `pesticide.manufacturing_refusal`.
* `services/knowledge_safety.py` classifies incoming questions for
  **manufacturing / synthesis**, **recipe** and **application-dosage** intent in
  English, Hindi and Odia, and the answer path returns the refusal/unavailable state
  rather than any generated text.
* `domain/safety/chemical_rules.py` was extended so the same manufacturability
  intent is refused in the pre-existing safety layer, not only in the new one.

---

## 7. Freshness

`models/farming_knowledge.py` stores `published_at`, `last_verified_at`,
`review_due_at` and derives `max_review_window_days` per category: regulatory
pesticide information expires faster than a historical practice.

`review_due_state()` maps a record to a label key (`CURRENT`, `REVIEW_DUE`,
`EXPIRED`, `UNVERIFIED`). Expired or unverifiable regulatory records are **not**
served as current: `entry_detail()` returns a non-`OK` state and the detail page
renders the `DATA_UNAVAILABLE` panel with the freshness reason. The freshness label
is shown on cards and detail pages, and `review_due_at` is printed next to the
sources.

---

## 8. Region context

`region_scope` plus `TechniqueRegion`/`PesticideTarget` rows. Known values include
`Odisha`, `Odisha, India`, `India`, `South Asia`, `Global`.

A region-specific practice is never generalised: when `region_scope` is not `Global`,
the detail page prints `knowledge.region_notice` stating that the practice is
documented for that region and applicability elsewhere is not established.

---

## 9. Search, filters, facets

`list_entries()` supports `q`, `category`, `crop`, `region`, `evidence`,
`language`, `mode`, `page`, `page_size` (capped at `MAX_PAGE_SIZE`) and always
returns a page plus totals — the whole knowledge base is never sent to a browser.

* Text search matches title, summary, common name and the practice/method text over
  **verified** records only.
* Facet values (`facets()`) come from the verified records actually present, so a
  filter can never offer a value that returns nothing.
* Empty results are honest: `DATA_UNAVAILABLE` when nothing is verified at all,
  `INSUFFICIENT_REAL_DATA` + `knowledge.no_results` when the filters matched nothing.

Indexes back the searches: `farming_techniques(category, review_status)`,
`slug`, `knowledge_sources.source_key`, `knowledge_translations(entity, language)`,
`farming_technique_crops(crop)`, `farming_technique_regions(region)`.

---

## 10. Multilingual system

Centralised, not scattered:

```
apps/api/agriq/i18n/
├── __init__.py          language registry, catalogs, translate(), request resolution
└── locales/
    ├── en.json          source language
    ├── or.json          Odia
    └── hi.json          Hindi
```

* `translate(key, code, **params)` resolves dotted keys with `{name}` interpolation
  and falls back to the key itself, so a missing string can never render as
  `undefined`. `browser_messages()` ships the same catalog to JS as
  `window.AGRIQ_I18N`, so `i18n.js` and the server agree by construction.
* Templates use the injected `t()`; JS uses `AgriqI18n.t()`.
* Resolution order: `?lang=` → stored profile preference → cookie → `Accept-Language`
  → English. Unknown values are never guessed; they fall through to the next source.
* The switcher is a plain GET form (`language_switcher()` macro), so it works with
  keyboard, screen readers and JavaScript disabled; it also preserves the reader's
  active filters while switching.
* Odia and Hindi catalogs are marked `TRANSLATION_PENDING_REVIEW` and every page
  shows `language_notice.draft`, so a draft interface translation is never presented
  as authoritative.
* **Authoritative agricultural text is never machine-translated in the browser.**
  A knowledge record is served translated only through a `knowledge_translations` row
  whose `review_status == REVIEWED`, added by the review CLI with a reviewer's name.
  When a translated field exists the source-language original is still shown for
  safety-critical sections, and untranslated fields fall back to the source language
  with the limitation stated.
* URLs, scientific names, active ingredients and official product names are not
  translated.

---

## 11. AI integration (retrieval-grounded, no invention)

```
question → safety classification → verified retrieval → evidence + attribution → explanation
```

* `retrieve_verified_knowledge(question, crop=...)` searches **verified** records and
  returns records, evidence rows and source metadata.
* `services/copilot_orchestrator.py` asks the knowledge service first. When evidence
  exists the answer is assembled from those records with source attribution. When
  nothing verified matches, the honest state is preserved
  (`PREPARATION_DATA_UNAVAILABLE` / `APPLICATION_DATA_UNVERIFIED` /
  `INSUFFICIENT_REAL_DATA` / `DATA_UNAVAILABLE`) — no substitute text is generated.
* Knowledge is labelled as knowledge: a record existing does not imply suitability
  for the caller's crop, stage or weather. Contextual suitability continues to come
  from the existing risk/intelligence services, which is why the copilot distinguishes
  `grounded knowledge` from `contextual recommendation`.

---

## 12. API

Authenticated (`get_current_user()`) surfaces, following the Phase 7.1 conventions
(401 `AUTH_UNAUTHORIZED` with structured `AUTH_*` codes, 404 for cross-user access):

```
GET  /farming-techniques                       HTML index (filters, facets, pagination)
GET  /farming-techniques/partials/results      HTML partial for lazy filter refresh
GET  /farming-techniques/technique/<slug>      HTML detail (farmer/student projection)
GET  /farming-techniques/pesticide/<slug>      HTML detail (pesticide safety frame)
GET  /api/v1/farming-techniques                verified listing (?category,&crop,&region,&evidence,&q,&lang,&mode,&page)
GET  /api/v1/farming-techniques/search         text search over verified records
GET  /api/v1/farming-techniques/categories     categories + verified counts
GET  /api/v1/farming-techniques/crops          crop facets
GET  /api/v1/farming-techniques/regions        region facets
GET  /api/v1/farming-techniques/evidence-levels evidence facets
GET  /api/v1/farming-techniques/sources        provenance index (attribution + licence notes)
GET  /api/v1/farming-techniques/status         coverage + awaiting-review counts
GET  /api/v1/farming-techniques/<kind>/<slug>  single verified record with evidence + sources
POST /api/v1/farming-techniques/ask            grounded question answering with safety guard
```

No ingestion or approval route exists.

---

## 13. Database

Migration `0008_farming_knowledge` (down_revision `0007_auth_sessions`), reversible
and non-destructive — it only creates new tables and adds nullable/owned columns:

| Table | Purpose |
| --- | --- |
| `farming_techniques` | one documented practice |
| `farming_technique_crops` | crop applicability (FK → technique) |
| `farming_technique_regions` | region applicability (FK → technique) |
| `farming_knowledge_evidence` | claim + evidence level + source section |
| `pesticide_information` | regulatory information records |
| `farming_pesticide_targets` | crop/target rows (FK → pesticide record) |
| `knowledge_translations` | reviewed translations, one row per field |

Extended in place (nullable columns only): `knowledge_sources`, `knowledge_chunks`.

`downgrade()` drops only the Phase 7.2 tables and the Phase 7.2 columns; the
upgrade → downgrade → upgrade cycle is covered by
`tests/integration/test_images.py::TestMigrationChain` and re-verified on the
release DB copy.

---

## 14. Data ingestion pipeline

```
dataset.json (curated, source-cited)
        ↓  import_farming_knowledge  (schema + provenance + safety validation)
knowledge_sources (PENDING_REVIEW) + farming_* rows (PENDING_REVIEW)
        ↓  review_knowledge --approve --reviewer "<name>"
VERIFIED rows + approved provenance + retrieval chunks
        ↓
production surfaces (HTML + API + copilot grounding)
```

`integrations/knowledge/farming_import.py` validates before it writes: required
fields, category and evidence vocabulary, slug uniqueness, `source_key` format,
`https` URL shape (no `javascript:`/`data:`/credential-bearing/loopback URLs),
publication/access dates, and the preparation/application status vocabulary. Records
that fail validation are reported and skipped — never defaulted, never invented.

`cli/review_knowledge.py` is the only approval path and requires a reviewer name.

Sources are curated by hand from documents that were actually retrieved; AGRIQ stores
short excerpts and its own summary with attribution rather than copying publications,
and no crawler runs against third-party sites.

---

## 15. Shipped dataset

`data/farming_knowledge/dataset.json` (`dataset_version` `2026.09-1`) contains
19 records written from 8 retrieved documents published by 6 organisations:

| Source | Organisation | Type |
| --- | --- | --- |
| DPPQS *Major Uses of Pesticides* — bio-insecticides | Directorate of Plant Protection, Quarantine & Storage | GOVERNMENT / REGULATORY |
| DPPQS *Major Uses of Pesticides* — bio-fungicides | Directorate of Plant Protection, Quarantine & Storage | GOVERNMENT / REGULATORY |
| DPPQS *Major Uses of Pesticides* — insecticides | Directorate of Plant Protection, Quarantine & Storage | GOVERNMENT / REGULATORY |
| DPPQS *Instructions on safe use of pesticides* | Directorate of Plant Protection, Quarantine & Storage | GOVERNMENT |
| ICAR-DWM SRI research bulletin 69 | ICAR | RESEARCH_INSTITUTE |
| TNAU *Organic farming — neem* | Tamil Nadu Agricultural University | AGRICULTURAL_UNIVERSITY |
| FAO *Crops and Drops* | FAO | INTERNATIONAL_ORGANIZATION |
| FAO IPM / conservation agriculture | FAO | INTERNATIONAL_ORGANIZATION |
| NITI Aayog natural-farming training manual | NITI Aayog | GOVERNMENT |

Every URL, the retrieval date and the specific claim each document supports are
listed in `docs/audits/PHASE7_2_KNOWLEDGE_AUDIT.md`, together with what each source
does **not** state.

The dataset is intentionally small. Coverage that is not source-verified is reported
as an honest state, not filled.

---

## 16. Honest states

Reused from `core/constants.py`: `DATA_UNAVAILABLE`, `INSUFFICIENT_REAL_DATA`,
`MODEL_NOT_VALIDATED`, `CONFIDENCE_NOT_CALIBRATED`, `PROBABILITY_NOT_CALIBRATED`,
`RECOMMENDATION_BLOCKED_INSUFFICIENT_DATA`, `INSUFFICIENT_SAMPLE_SIZE`,
`PASSWORD_RESET_EMAIL_UNAVAILABLE`.
Added for knowledge: `PREPARATION_DATA_UNAVAILABLE`, `APPLICATION_DATA_UNVERIFIED`.

Precedence remains: real data > data quality > methodology > validation >
explainability > model complexity.

---

## 17. Local development

```bash
cd apps/api
python -m pytest -q                                  # full suite, including Phase 7.2
python -m agriq.cli.import_farming_knowledge --dataset ../../data/farming_knowledge/dataset.json
python -m agriq.cli.review_knowledge --list
```

No environment variable is required by this feature. Nothing new is fetched at
request time, so the knowledge feature behaves identically offline and online.

---

## 18. Testing

`tests/unit/test_i18n.py` — catalog integrity for all three languages, key parity,
interpolation, fallback, resolution order, no untranslated-key leakage.

`tests/integration/test_farming_knowledge.py` — dataset validation (provenance,
evidence, region, preparation/application states, forbidden fields), import →
review → visibility, double review gate, search/filter/facet/pagination behaviour,
farmer vs student projection, i18n rendering, freshness/expiry, safety guard
(manufacturing, recipe, dosage) in all three languages, authorization (401/404,
no unverified leakage), and the invariant that no dose or preparation text is served
without a cited source.
