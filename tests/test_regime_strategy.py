import numpy as np
import pandas as pd

from cli.experiment.strategies.regime import regime_exposure_series


def _close(values):
    idx = pd.date_range("2020-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype="float64")


def test_binary_full_above_ma_cash_below():
    # rising then falling around a short MA window
    up = list(range(1, 21))
    down = list(range(20, 0, -1))
    s = regime_exposure_series(_close(up + down), mode="binary", ma_window=5)
    # warmup (first <5) -> 1.0
    assert (s.iloc[:4] == 1.0).all()
    # deep in the uptrend -> close > MA -> 1.0; deep in downtrend -> 0.0
    assert s.iloc[18] == 1.0
    assert s.iloc[-2] == 0.0


def test_graded_has_chop_tier():
    flat = [100.0] * 30
    s = regime_exposure_series(_close(flat), mode="graded", ma_window=5, band=0.05, chop_exposure=0.5)
    # flat price == MA -> within band -> chop tier
    assert s.iloc[-1] == 0.5


def test_cross_uses_fast_vs_slow():
    up = list(range(1, 41))
    s = regime_exposure_series(_close(up), mode="cross", ma_window=20, ma_fast=5)
    # steady uptrend: fast MA > slow MA -> 1.0 once both windows are warm
    assert s.iloc[-1] == 1.0


def test_vol_target_scales_down_high_vol():
    rng = np.random.default_rng(0)
    calm = _close(100 + np.cumsum(rng.normal(0, 0.1, 400)))
    s_off = regime_exposure_series(calm, mode="binary", ma_window=5)
    s_on = regime_exposure_series(calm, mode="binary", ma_window=5, vol_target=0.0001, vol_lookback=20)
    # a tiny vol_target forces heavy downscaling vs off
    assert s_on.iloc[-1] < s_off.iloc[-1]
    assert (s_on >= 0).all() and (s_on <= 1).all()


def test_multiplier_bounded_unit_interval():
    s = regime_exposure_series(_close(list(range(1, 60))), mode="binary", ma_window=10)
    assert s.min() >= 0.0 and s.max() <= 1.0
