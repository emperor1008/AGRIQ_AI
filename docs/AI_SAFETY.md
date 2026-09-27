# AI Safety (Phase 2, extended in Phase 7.2)

AGRIQ's safety rules are deterministic code, evaluated **before** any LLM
call. The model can add explanation but can never weaken or bypass them.

## Agricultural knowledge answers (Phase 7.2)

`services/knowledge_safety.py` adds a second, independent guard in front of the
knowledge base, and `domain/safety/chemical_rules.py` recognises the same
manufacturability intent in the pre-existing pipeline:

| Intent | Detection | Response |
|---|---|---|
| How to make/synthesise/formulate a pesticide | `KNOWLEDGE_MANUFACTURING_REFUSED` patterns in English, Hindi and Odia | `KNOWLEDGE_MANUFACTURING_REFUSED` — refusal, no steps, no quantities, safe-use information offered instead |
| A preparation recipe | recipe/home-made/natural-spray patterns | `PREPARATION_DATA_UNAVAILABLE` unless a reviewed source documents that exact preparation |
| An application rate, dilution or interval | dosage/how-much/how-often patterns | `APPLICATION_DATA_UNVERIFIED` unless a current authority states it for that record |

Grounding rule: the knowledge answer path retrieves **only** review-verified records
whose provenance row is approved, and returns the passages with their sources. It
does not call a language model, so there is nothing to hallucinate with. If nothing
verified matches, the answer is the named unavailable state explained in the reader's
language. A dose is never inferred from another record, crop or active ingredient, and
modern pesticide records always carry the label notice plus the manufacturing refusal
(see [knowledge-architecture.md](knowledge-architecture.md) §6).

The end-to-end behaviour is verified by `scripts/check_knowledge_safety.py`
(65 checks: manufacturing, recipe, dosage, invented-source and unverified-leak probes
in three languages).

## Hard prohibitions (enforced in `domain/safety/chemical_rules.py`)

The copilot never:

- Prescribes an exact pesticide or fertiliser quantity without (a) an
  approved knowledge passage containing a verified regional dosage AND
  (b) a confirmed field area. In Phase 2 no dosage evidence has been
  ingested, so **every exact-dosage request is blocked** and escalated.
- Recommends chemical mixing without label-verified support (blocked).
- Gives spray guidance when weather data is missing or unsafe
  (wind ≥ 15 km/h heuristic, active rain, extreme heat — stated as
  operational heuristics, not regulatory limits).
- Claims a definite diagnosis from text symptoms.
- Presents general educational content as field-specific certainty.
- Hides uncertainty: confidence basis and missing information are always
  returned.
- Fabricates government approval, citations or research results.

Chemical exposure mentions (`poison`, `drank`, `inhale`, …) immediately
short-circuit the pipeline: an immediate-urgency handover message is
returned **without any model call**.

## Escalation policy (`domain/safety/escalation.py`)

Escalate to KVK / agriculture officer / agronomist when any of:

- Symptoms are severe or reported to be spreading rapidly
- The crop condition is unsupported by approved evidence
- Evidence conflicts
- Exact chemical selection/dosage is requested
- Poisoning or unsafe chemical exposure is mentioned (immediate)
- Reported crop loss appears substantial
- Confidence level is `low` (below the release threshold)

Escalation responses carry the handover message and
`requires_expert_confirmation: true`; they are never presented as
complete answers.

## LLM containment

- The prompt states the verified context and forbids invention of weather,
  prices, soil values, diagnoses or citations.
- Only approved knowledge excerpts may be cited; unapproved/absent evidence
  yields "verified guidance is unavailable", never an invented citation.
- Prompt-injection attempts in the farmer's question are stored as inert
  user text and cannot alter ownership checks, tool selection or guardrails
  (all are code-side and session-derived).
- Provider failure categories (`not_configured`, `timeout`, `api_error`,
  `invalid_response`) all map to one farmer-facing message: "The AI
  assistant is temporarily unavailable." No scripted fallback is ever
  labelled as AI output.

## Data protection

- user id always comes from the session; ownership is re-verified at
  repository level on every request.
- Conversation memory excludes other users' data by construction (queries
  are scoped to the caller's ids) and is capped in size.
- No API keys, provider payloads or secrets are stored in conversations,
  messages, assistant runs or logs.
- `assistant_runs` records ids, versions and status only — never prompts,
  keys or full provider responses.

## Evaluation status

Not yet validated. Until agronomist-reviewed evaluation exists, no accuracy
percentage or benchmark score is displayed anywhere (see
docs/EVALUATION.md).
