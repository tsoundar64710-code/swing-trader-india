"""Application-specific exceptions."""


class SwingTraderError(Exception):
    """Base error for the application."""


class SettingsError(SwingTraderError):
    """Invalid or unreadable settings."""


class DataValidationError(SwingTraderError):
    """Market data failed schema/integrity validation."""


class InsufficientDataError(SwingTraderError):
    """Not enough valid data to compute or decide."""


class RiskLimitError(SwingTraderError):
    """A proposed trade violates a configured risk limit."""


class OrderError(SwingTraderError):
    """Simulated order rejected or in an invalid state."""


class MigrationError(SwingTraderError):
    """Database migration failed."""


class ProviderError(SwingTraderError):
    """A data provider failed or is unavailable."""
