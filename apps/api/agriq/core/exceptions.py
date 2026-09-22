"""Application exception types with safe user-facing messages.

Routes and error handlers translate these exceptions into safe responses;
internal detail is logged but never returned to the browser.
"""
from __future__ import annotations


class AgriqError(Exception):
    """Base class for AGRIQ AI application errors."""

    #: Safe message shown to users.
    user_message = "Something went wrong. Please try again."
    #: HTTP status used when converted to an API response.
    status_code = 500

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        # The primary message is farmer-facing by convention across AGRIQ
        # (schemas/services raise with the text users should see), so it also
        # becomes the safe user-facing message. An explicit ``user_message=``
        # still wins when internal detail and public text must differ.
        if message:
            self.user_message = message
        if user_message:
            self.user_message = user_message


class ProviderUnavailableError(AgriqError):
    """An external provider (weather/market/AI) failed or is not configured."""

    user_message = "The data provider is temporarily unavailable."
    status_code = 503


class WeatherUnavailableError(ProviderUnavailableError):
    user_message = "Live weather is temporarily unavailable."


class MarketUnavailableError(ProviderUnavailableError):
    user_message = "Official mandi data is unavailable."


class AssistantUnavailableError(ProviderUnavailableError):
    user_message = "Assistant is temporarily unavailable."


class ValidationError(AgriqError):
    """User input failed validation."""

    user_message = "Invalid input."
    status_code = 400


class InvalidImageError(ValidationError):
    user_message = "Use a clear JPG, PNG or WebP under 5 MiB."


class InvalidCSRFError(ValidationError):
    user_message = "Invalid or missing CSRF token."


class NotFoundError(AgriqError):
    """A requested resource does not exist (or is not visible to the caller)."""

    user_message = "The requested record was not found."
    status_code = 404


class ForbiddenError(AgriqError):
    """The record exists but belongs to another farmer."""

    user_message = "You do not have access to this record."
    status_code = 403


__all__ = [
    "AgriqError",
    "ProviderUnavailableError",
    "WeatherUnavailableError",
    "MarketUnavailableError",
    "AssistantUnavailableError",
    "ValidationError",
    "InvalidImageError",
    "InvalidCSRFError",
    "NotFoundError",
    "ForbiddenError",
]
