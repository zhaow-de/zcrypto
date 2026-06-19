"""BTC-trend regime overlay: pure exposure logic + a TopkDropout wrapper.

The pure ``regime_exposure_series`` maps a benchmark close series to a per-date
gross-exposure multiplier in [0, 1]; ``RegimeGatedTopkStrategy`` is the thin qlib
wrapper that applies it through ``get_risk_degree``. See docs/specs/00011.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_TRADING_DAYS = 365  # crypto trades 24/7


def regime_exposure_series(
    close: pd.Series,
    *,
    mode: str = "binary",
    ma_window: int = 200,
    ma_fast: int | None = None,
    band: float = 0.0,
    chop_exposure: float = 0.5,
    vol_target: float | None = None,
    vol_lookback: int = 30,
) -> pd.Series:
    close = close.astype("float64").sort_index()
    sma = close.rolling(ma_window).mean()
    if mode == "binary":
        mult = (close > sma).astype("float64")
    elif mode == "graded":
        mult = pd.Series(chop_exposure, index=close.index, dtype="float64")
        mult[close > sma * (1 + band)] = 1.0
        mult[close < sma * (1 - band)] = 0.0
    elif mode == "cross":
        if ma_fast is None:
            raise ValueError("mode='cross' requires ma_fast")
        sma_fast = close.rolling(ma_fast).mean()
        mult = (sma_fast > sma).astype("float64")
    else:
        raise ValueError(f"unknown regime mode: {mode!r}")
    # Warmup (any SMA NaN) -> cannot gate -> stay fully invested.
    warm = sma.isna() | (close.rolling(ma_fast).mean().isna() if mode == "cross" else False)
    mult[warm] = 1.0
    if vol_target is not None:
        realized = close.pct_change().rolling(vol_lookback).std() * np.sqrt(_TRADING_DAYS)
        scale = (vol_target / realized).clip(upper=1.0)
        mult = mult * scale.fillna(1.0)
    return mult.clip(0.0, 1.0)
