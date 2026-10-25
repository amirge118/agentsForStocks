import numpy as np
import pandas as pd
import pytest


def make_ohlcv(closes: list[float] | np.ndarray, volume: float = 1_000_000) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    index = pd.bdate_range("2025-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.01,
            "Low": closes * 0.99,
            "Close": closes,
            "Volume": np.full(len(closes), volume),
        },
        index=index,
    )


@pytest.fixture
def uptrend() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return make_ohlcv(100 * np.cumprod(1 + 0.004 + rng.normal(0, 0.004, 250)))


@pytest.fixture
def downtrend() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return make_ohlcv(100 * np.cumprod(1 - 0.004 + rng.normal(0, 0.004, 250)))
