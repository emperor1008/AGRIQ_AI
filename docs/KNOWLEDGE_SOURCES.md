# Knowledge Sources (Phase 2)

## Registry model

Knowledge lives in two tables:

- `knowledge_sources` — one row per document with full provenance:
  `source_key`, `title`, `organisation`, `source_url`, `document_type`,
  `crop`, `region`, `language`, `publication_date`, `licence_note`,
  `checksum`, `version`, `review_status`, `retrieved_at`, `reviewed_at`.
- `knowledge_chunks` — meaningful sections of one source with
  `section_reference`, `content`, `content_hash` and (currently always NULL)
  `embedding_reference`.

## Review workflow

Allowed statuses: `pending_review` → `approved` / `rejected`, plus
`archived`. **Only `approved` sources are retrievable** — the gate is in the
retriever's SQL, not in the UI. Ingestion always creates rows as
`pending_review`; nothing is auto-approved. Re-ingesting a changed document
(checksum mismatch) demotes an approved source back to `pending_review`.

## Approved organisation allowlist

Ingestion rejects any manifest entry whose organisation is not:

- ICAR (incl. ICAR-CIARI, ICAR-NRRI, ICAR-CRRI, ICAR-IIRI)
- Department of Agriculture and Farmers' Empowerment, Government of Odisha
- Odisha University of Agriculture and Technology (where reuse is allowed)
- KVK Odisha
- Government of Odisha / Government of India / Ministry of Agriculture and
  Farmers Welfare

Permitted document types: advisory, package of practices, official
pesticide labels (where legally reusable), peer-reviewed open-access
research, extension material, government circulars.

Explicitly banned: anonymous blogs, SEO agriculture sites, social media,
LLM-generated documents, unlicensed dosage tables, content without
provenance.

## Ingestion

```powershell
cd apps\api
python -m agriq.cli.ingest_knowledge --manifest ../../data/source_manifest.json
```

Rules enforced by `integrations/knowledge/ingestion.py`:

- Only allowlisted manifest sources are downloaded (validated first; an
  invalid manifest aborts before any network call).
- 30 s timeout, 2 retries with backoff, 25 MB size ceiling.
- SHA-256 checksum stored; duplicate (unchanged) ingestion is skipped.
- Text extraction rejects empty/corrupted documents (< 200 chars).
- Content is split by meaningful section (headings, else paragraphs);
  every chunk keeps its section reference and content hash.
- Raw documents are archived under `KNOWLEDGE_STORAGE_PATH/raw/` — outside
  the public static tree, never browser-reachable.
- Per-source failures are reported and isolated; no partial row is marked
  ingested.
- No credentials are ever logged.

## Retrieval strategy

`integrations/knowledge/retriever.py` (lexical, Phase 2 approved method):

- Candidate set: **approved** sources only, filtered by crop.
- Scoring: query-term coverage + phrase bonus + district/state relevance +
  publication recency + language match.
- Threshold: `KNOWLEDGE_MIN_RELEVANCE_SCORE` (default 0.18). Below it the
  retriever returns an explicit "no approved evidence" result and the
  copilot says verified guidance is unavailable — the LLM may not invent a
  citation.
- Every passage carries: source id, title, organisation, section, publication
  date, relevance score, retrieval timestamp.

Semantic retrieval: not implemented in Phase 2 (no embedding provider);
`embedding_reference` is the future hook. The API honestly reports
`method: "lexical"`.

## Adding a new source

1. Add a fully-attributed entry to `data/source_manifest.json` (organisation
   must be in the allowlist).
2. Run the ingestion CLI.
3. A human reviewer verifies content and sets `review_status='approved'`
   (with `reviewed_at`) directly in the database.
4. The source becomes retrievable on the next request.
