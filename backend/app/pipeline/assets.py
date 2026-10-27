"""FundDetector — asks the providers whether a symbol is a fund (see app/domain/assets.py)."""

import logging

from app.domain.assets import is_fund
from app.providers.errors import ProviderError
from app.providers.yfinance import YFinanceClient

logger = logging.getLogger(__name__)


class FundDetector:
    def __init__(self, yfinance: YFinanceClient) -> None:
        self._yfinance = yfinance

    async def __call__(self, symbol: str) -> bool:
        # The same cached Ticker.info the agents read, so this costs no extra call
        try:
            return is_fund(await self._yfinance.get_info(symbol))
        except ProviderError as exc:
            logger.warning(
                "Could not tell whether the symbol is a fund; running every agent",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return False
