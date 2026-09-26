"""Farm-to-Market Optimizer domain package (Phase 6).

Deterministic, provider-agnostic market intelligence. Nothing here calls a
provider, touches the database or sees an LLM: modules take plain records in and
return plain, evidence-carrying structures.

* ``normalization`` — unit/price/commodity normalization and data-quality
  quarantine. Suspicious provider values are FLAGGED, never silently repaired.
* ``freshness`` — per-source freshness thresholds and the provenance block
  attached to every market output.
* ``trend`` — trend and volatility computed from real dated observations.
* ``forecasting`` — chronological, baseline-compared price forecasting that
  refuses to publish a number without enough real history.
* ``suitability`` — agronomic crop suitability from the existing crop catalogs
  and district agro-climatic profiles.
* ``decision`` — economics (gross vs incomplete net), transparent sell/hold and
  market comparison with an explicit logistics-data limitation.

The invariant for the whole package: NO DATA → NO CLAIM. Every capability can
honestly answer "insufficient verified data" and must never invent a value.
"""
