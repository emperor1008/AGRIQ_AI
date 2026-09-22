"""Gemini generative-AI integration (ARC-06 / Phase 2 §1).

The adapter is used only when ``GEMINI_API_KEY`` is configured. Any failure
returns an explicit *unavailable* :class:`ProviderResult` — a scripted answer
is never presented as a Gemini response. The legacy ``generate_answer``
helper is preserved for the Phase 1 student-mode path.
"""
from __future__ import annotations

from typing import Any, Mapping

import requests

from ...core.constants import GEMINI_GENERATE_URL
from ...core.logging import get_logger
from .provider import ProviderResult

logger = get_logger("integrations.gemini")


def _prompt(question: str, mode: str, context: Mapping[str, Any]) -> str:
    context_text = "\n".join(f"- {k}: {v}" for k, v in context.items() if v not in (None, ""))
    if mode == "farmer":
        role = "You are AGRIQ AI, a practical agriculture assistant for Indian farmers, especially Odisha."
        rules = (
            "Give simple actionable advice. Distinguish observations from diagnosis. "
            "Do not invent pesticide doses, legal claims, prices, or weather. "
            "For chemicals, tell the user to follow the product label and local agriculture guidance. "
            "Mention when an agronomist or extension officer should verify a diagnosis."
        )
    else:
        role = "You are AGRIQ AI Research Assistant for agriculture students and beginner researchers."
        rules = (
            "Explain concepts clearly at beginner level, then add technical depth only when useful. "
            "Do not fabricate citations or research results. If sources are requested, say that sources must be verified."
        )
    return (
        f"{role}\n{rules}\n\nCurrent context:\n{context_text or '- none'}\n\n"
        f"User question:\n{question}\n\n"
        "Answer in a clear, structured format with short headings and bullets where useful."
    )


def is_configured(api_key: str | None) -> bool:
    """True when a Gemini API key is present."""
    return bool((api_key or "").strip())


def generate_answer(
    question: str,
    mode: str,
    context: Mapping[str, Any],
    api_key: str | None,
    model: str,
) -> str | None:
    """Legacy helper: call Gemini generateContent. Returns None when failed."""
    key = (api_key or "").strip()
    if not key:
        return None
    url = GEMINI_GENERATE_URL.format(model=model) + f"?key={key}"
    payload = {"contents": [{"parts": [{"text": _prompt(question, mode, context)}]}]}
    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as exc:
        logger.warning("gemini_failed error=%s", type(exc).__name__)
        return None


# ---------------------------------------------------------------------------
# Phase 2 provider contract
# ---------------------------------------------------------------------------

def generate(
    prompt: str,
    *,
    api_key: str | None,
    model: str,
    timeout_seconds: int = 30,
    system: str | None = None,
) -> ProviderResult:
    """Call Gemini and return an explicit success/unavailable result.

    ``error_category`` is one of: not_configured | timeout | api_error |
    invalid_response. The orchestrator maps every unavailable category to the
    farmer-facing message "The AI assistant is temporarily unavailable."
    """
    key = (api_key or "").strip()
    if not key:
        return ProviderResult(available=False, error_category="not_configured",
                              reason="Gemini API key is not configured.")

    url = GEMINI_GENERATE_URL.format(model=model) + f"?key={key}"
    payload: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    try:
        response = requests.post(url, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        logger.warning("gemini_timeout model=%s", model)
        return ProviderResult(available=False, error_category="timeout",
                              reason="The AI provider did not respond in time.")
    except requests.exceptions.RequestException as exc:
        logger.warning("gemini_api_error error=%s", type(exc).__name__)
        return ProviderResult(available=False, error_category="api_error",
                              reason="The AI provider returned an error.")
    except ValueError as exc:
        logger.warning("gemini_invalid_json error=%s", type(exc).__name__)
        return ProviderResult(available=False, error_category="invalid_response",
                              reason="The AI provider response could not be read.")
    except Exception as exc:  # noqa: BLE001 — a provider failure must never crash a turn
        logger.warning("gemini_unexpected error=%s", type(exc).__name__)
        return ProviderResult(available=False, error_category="api_error",
                              reason="The AI provider returned an error.")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        logger.warning("gemini_invalid_response structure_missing")
        return ProviderResult(available=False, error_category="invalid_response",
                              reason="The AI provider response was empty or malformed.")
    if not text:
        return ProviderResult(available=False, error_category="invalid_response",
                              reason="The AI provider returned an empty answer.")
    return ProviderResult(available=True, text=text, provider="gemini", model=model)


__all__ = ["is_configured", "generate_answer", "generate", "ProviderResult"]
