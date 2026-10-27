class ProviderError(Exception):
    """An external data source failed after all retries, or refused the request."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        # The HTTP status when the source answered (e.g. FMP's 402 for "not in your plan")
        self.status = status


class RetryableError(ProviderError):
    """A transient failure (timeout, connection error, 429, 5xx) worth retrying."""


class QuotaExceededError(ProviderError):
    """A provider's call budget (e.g. FMP's daily free-tier limit) is used up."""
