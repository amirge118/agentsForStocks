class ProviderError(Exception):
    """An external data source failed after all retries, or refused the request."""


class RetryableError(ProviderError):
    """A transient failure (timeout, connection error, 429, 5xx) worth retrying."""


class QuotaExceededError(ProviderError):
    """A provider's call budget (e.g. FMP's daily free-tier limit) is used up."""
