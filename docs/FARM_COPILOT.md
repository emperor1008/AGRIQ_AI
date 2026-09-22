# AGRIQ AI Farm Copilot (Phase 2)

The Farm Copilot is AGRIQ's personalised, evidence-backed agriculture
assistant. It runs inside the existing conversational interface (farmer
mode) and is served by the versioned API `POST /api/v1/copilot/messages`.

Status: **implemented as described here; evaluation not yet validated**
(see docs/EVALUATION.md).

## What makes it a copilot (not a chatbot)

1. It loads the **authenticated farmer's verified context** — profile,
   farm, field, soil records, active crop cycle, stage, recent observations,
   previous recommendations and their outcomes.
2. It uses **real external data** (Open-Meteo weather for the field's own
   coordinates; official AGMARKNET mandi records) with provider, timestamp
   and freshness carried on every value.
3. It grounds every answer in **approved agricultural knowledge sources**
   with citations; unapproved sources are never retrievable.
4. It applies **deterministic safety guardrails in code** — the LLM can
   never override them.
5. It reports **what it does not know** ("Verified data is currently
   unavailable.", "No verified soil-test value has been recorded.") instead
   of guessing.

## Orchestration pipeline (single entry point)

`services/copilot_orchestrator.py::run_copilot` executes, in order:

1. Authenticate (route layer guarantees the session user).
2. Verify ownership of the requested field / crop cycle (repository-level
   ownership checks; a foreign id is a plain 404).
3. Load the Shared Farmer Context (`services/farmer_context.py`).
4. Detect intent deterministically (`domain/advisory/intent.py` — rule-based,
   EN/HI/OR keywords; low confidence asks one clarifying question).
5. Invoke only the required internal tools (weather / market / knowledge).
6. Retrieve approved knowledge (`integrations/knowledge/retriever.py`),
   lexical scoring over approved chunks with a configurable relevance
   threshold.
7. Validate freshness; stale/cached/unavailable states are labelled, never
   relabelled as live.
8. Apply safety guardrails (`domain/safety/chemical_rules.py`,
   `domain/safety/escalation.py`) **before** any model call.
9. Build the structured evidence package (every item: type, source,
   timestamp, freshness).
10. Send only the minimum necessary context to Gemini
    (`build_copilot_prompt`; conversation memory is capped, secrets are
    never included).
11. Validate the model response (provider contract returns success or an
    explicit unavailable state).
12. Persist conversation, message evidence, an `assistant_runs` provenance
    row (context record ids, retrieved source ids, prompt version, status)
    and — when confidence ≥ medium — a structured `recommendations` row.
13. Return the farmer-friendly payload (or the compact variant).

## Response contract

```json
{
  "ok": true,
  "conversation_id": "hex uuid",
  "message_id": "hex uuid",
  "answer": "…",
  "recommended_actions": ["…"],
  "reasons": ["…"],
  "evidence": [{"type": "weather_forecast", "source": "Open-Meteo",
                "observed_or_retrieved_at": "ISO", "freshness": "live"}],
  "confidence": {"level": "medium", "score": 0.72,
                 "basis": "…", "calculation_version": "copilot-confidence-v1"},
  "missing_information": ["…"],
  "requires_expert_confirmation": false,
  "valid_until": "ISO",
  "language": "or",
  "sources": [{"source_id": 3, "title": "…", "organisation": "ICAR",
               "section": "…", "publication_date": "YYYY-MM-DD",
               "relevance": 0.41, "retrieved_at": "ISO"}],
  "recommendation_id": 12
}
```

## Confidence formula (copilot-confidence-v1)

```
score = 0.30 * context_completeness        (verified context fields present / 7)
      + 0.20 * weather_factor              (1.0 fresh, 0.5 stale/cached, 0 absent)
      + 0.25 * knowledge_factor            (top approved retrieval relevance)
      + 0.10 * direct_observation          (1 if a farmer observation exists)
      - 0.15 if conflicting evidence
      - 0.08 per missing critical input    (max 0.24)
level: high ≥ 0.75, medium ≥ 0.50, low < 0.50
```

Every response carries `calculation_version`; the basis sentence lists
exactly which factors applied. Low confidence never auto-persists an
actionable recommendation — it triggers clarification or escalation.

## Supported intents

Deterministic routing over EN/HI/OR keywords for: today's farm action,
irrigation, weather/rainfall, sowing preparation, transplanting, crop-stage
care, nutrient symptoms, pest symptoms, disease symptoms, weed management,
harvest readiness, post-harvest handling, soil information, market-price
lookup, previous recommendation, record observation, general agriculture,
expert help. Intent confidence below threshold returns one short clarifying
question instead of guessing.

## Conversation memory

Only the current conversation (last 6 turns, trimmed) plus the verified
active context is eligible for the prompt. The farmer's full history is
never sent. The provenance row records which record ids were shared.

## Low-bandwidth mode

`POST /api/v1/copilot/messages?response_mode=compact` returns: one action,
up to three reasons, data freshness, one warning/limitation, one follow-up
step. No images; payload minimised. The unsent question stays in the input
field on network failure (client-side retry).

## Known limitations

- Gemini failure/unconfigured → "The AI assistant is temporarily
  unavailable." No scripted substitute is ever labelled as AI.
- Semantic (embedding) retrieval is **not** implemented; lexical retrieval
  is the approved method. `knowledge_chunks.embedding_reference` stays NULL.
- Evaluation is **not yet validated** (docs/EVALUATION.md) — no accuracy
  figure is claimed anywhere.
- Voice input, disease-image diagnosis, outbreak prediction, market
  forecasting, demand prediction, sell/hold timing and logistics are
  explicitly **out of scope** for Phase 2.
