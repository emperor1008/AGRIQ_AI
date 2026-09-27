"""Opaque token helpers (Phase 7.1).

Session and password-reset tokens are random values generated with
``secrets.token_urlsafe`` and stored **only** as SHA-256 hex digests. Lookups
compare digests with ``hmac.compare_digest`` so a timing signal never reveals how
much of a token matched. Raw token values are returned to the caller once and
never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

#: 32 random bytes → 43 url-safe characters, ~256 bits of entropy.
TOKEN_BYTES = 32


def generate_token(nbytes: int = TOKEN_BYTES) -> str:
    """Return a new cryptographically secure opaque token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(raw: str | None) -> str:
    """SHA-256 hex digest of a token (the only form ever persisted)."""
    return hashlib.sha256(str(raw or "").encode("utf-8")).hexdigest()


def token_matches(stored_hash: str | None, raw: str | None) -> bool:
    """Constant-time comparison of a stored digest with a submitted raw token."""
    if not stored_hash or not raw:
        return False
    return hmac.compare_digest(str(stored_hash), hash_token(raw))


def hash_address(value: str | None, *, salt: str = "") -> str | None:
    """Salted SHA-256 of a client address, for abuse triage without storing it."""
    if not value:
        return None
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()


__all__ = ["TOKEN_BYTES", "generate_token", "hash_token", "token_matches", "hash_address"]
