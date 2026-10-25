"""Quick daily scan metrics: price change, SMA position, volume spike."""

from dataclasses import dataclass

import pandas as pd

VOLUME_SPIKE_RATIO = 2.0


@dataclass(frozen=True)
class ScanMetrics:
    price: float | None
    change_pct: float | None
    sma_20: float | None
    sma_50: float | None
    price_vs_sma20_pct: float | None
    volume_ratio: float | None

    @property
    def volume_spike(self) -> bool:
        return self.volume_ratio is not None and self.volume_ratio > VOLUME_SPIKE_RATIO


def scan_metrics(info: dict, history: pd.DataFrame) -> ScanMetrics:
    price = info.get("regularMarketPrice")
    prev_close = info.get("previousClose")
    volume = info.get("volume")
    avg_volume = info.get("averageVolume")

    sma_20 = sma_50 = vs_sma20 = None
    if not history.empty:
        closes = history["Close"]
        sma_20 = round(float(closes.tail(20).mean()), 2)
        sma_50 = round(float(closes.tail(50).mean()), 2) if len(closes) >= 50 else None
        if price and sma_20:
            vs_sma20 = round((price / sma_20 - 1) * 100, 2)

    return ScanMetrics(
        price=price,
        change_pct=round((price / prev_close - 1) * 100, 2) if price and prev_close else None,
        sma_20=sma_20,
        sma_50=sma_50,
        price_vs_sma20_pct=vs_sma20,
        volume_ratio=round(volume / avg_volume, 2) if volume and avg_volume else None,
    )
