from __future__ import annotations


class BotError(Exception):
    """Base class for domain-specific bot errors."""


class ConfigurationError(BotError):
    """Raised when environment configuration is invalid."""


class RepositoryError(BotError):
    """Raised when persistence operations fail."""


class ServiceError(BotError):
    """Raised when service logic fails."""


class ExternalAPIError(ServiceError):
    """Raised when external API calls fail."""
