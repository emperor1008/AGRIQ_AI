"""Risk-engine analyzers package (Phase 5).

Each analyzer is a deterministic, versioned rule module producing the same
normalized assessment contract (see ``base.Assessment``). Analyzers never
call providers, never touch the database and never see the LLM.
"""
