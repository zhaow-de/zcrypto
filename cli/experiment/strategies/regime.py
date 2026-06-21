"""BTC-trend regime overlay: pure exposure logic + a TopkDropout wrapper.

The pure ``regime_exposure_series`` maps a benchmark close series to a per-date
gross-exposure multiplier in [0, 1]; ``RegimeGatedTopkStrategy`` is the thin qlib
wrapper that applies it through ``get_risk_degree``. See docs/specs/00011.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy, WeightStrategyBase

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


class RegimeGatedTopkStrategy(TopkDropoutStrategy):
    """TopkDropout whose gross exposure is scaled by a BTC-trend regime multiplier."""

    def __init__(
        self,
        *,
        regime_mode="binary",
        regime_benchmark="BTCUSDT",
        regime_ma_window=200,
        regime_ma_fast=None,
        regime_band=0.0,
        chop_exposure=0.5,
        vol_target=None,
        vol_lookback=30,
        **kwargs,
    ):
        super().__init__(**kwargs)  # topk, n_drop, hold_thresh, signal, risk_degree, ...
        self.regime_mode = regime_mode
        self.regime_benchmark = regime_benchmark
        self.regime_ma_window = regime_ma_window
        self.regime_ma_fast = regime_ma_fast
        self.regime_band = regime_band
        self.chop_exposure = chop_exposure
        self.vol_target = vol_target
        self.vol_lookback = vol_lookback
        # qlib's TopkDropoutStrategy sizes buys with the RAW self.risk_degree attribute (not
        # get_risk_degree()); capture the base so generate_trade_decision can push the gated
        # value onto the attribute per step. See _generate / .tmp/qlib-bug-*.md.
        self._base_risk_degree = self.risk_degree
        self._exposure = self._build_exposure()

    def _build_exposure(self) -> pd.Series:
        from qlib.data import D

        df = D.features([self.regime_benchmark], ["$close"], freq="day")
        close = df["$close"].droplevel(0)  # drop instrument level -> date-indexed
        return regime_exposure_series(
            close,
            mode=self.regime_mode,
            ma_window=self.regime_ma_window,
            ma_fast=self.regime_ma_fast,
            band=self.regime_band,
            chop_exposure=self.chop_exposure,
            vol_target=self.vol_target,
            vol_lookback=self.vol_lookback,
        )

    def _mult_for_step(self, trade_step=None) -> float:
        step = trade_step if trade_step is not None else self.trade_calendar.get_trade_step()
        _, date = self.trade_calendar.get_step_time(step)
        date = pd.Timestamp(date).normalize()
        exp = self._exposure
        # exact date, else carry forward the most recent prior value, else full.
        if date in exp.index:
            return float(exp.loc[date])
        prior = exp.loc[:date]
        return float(prior.iloc[-1]) if len(prior) else 1.0

    def get_risk_degree(self, trade_step=None):
        return self._base_risk_degree * self._mult_for_step(trade_step)

    def generate_trade_decision(self, execute_result=None):
        # WORKAROUND for a qlib inconsistency: TopkDropoutStrategy.generate_trade_decision sizes
        # buys with the RAW self.risk_degree attribute, NOT self.get_risk_degree() (see
        # .tmp/qlib-bug-topkdropout-ignores-get-risk-degree.md). Overriding get_risk_degree alone
        # is therefore inert on a TopkDropout book. Push THIS step's regime-gated value onto the
        # attribute before delegating, so the buy sizing actually reflects the gate.
        self.risk_degree = self.get_risk_degree()
        return super().generate_trade_decision(execute_result)


def inverse_vol_weights(vols: pd.Series) -> pd.Series:
    """Risk-parity-lite weights: proportional to 1/vol over finite, strictly-positive vols,
    normalized to sum to 1. Non-finite or <=0 vols get weight 0 (then the rest renormalize);
    if none are usable, fall back to equal weights over the input index.
    """
    vols = vols.astype("float64")
    inv = 1.0 / vols
    good = np.isfinite(inv) & (vols > 0)
    if not good.any():
        n = len(vols)
        return pd.Series(1.0 / n, index=vols.index) if n else pd.Series(dtype="float64")
    inv = inv.where(good, 0.0)
    return inv / inv.sum()


class VolWeightedRegimeStrategy(WeightStrategyBase):
    """Inverse-vol (risk-parity-lite) weights over the universe, gated by the BTC-trend regime.

    Cross-sectional weights come from trailing per-name realized vol, looked up STRICTLY BEFORE
    each trade date (no look-ahead). Total exposure is scaled by the regime multiplier via
    ``get_risk_degree``, which ``WeightStrategyBase``'s order generator honors natively.
    """

    def __init__(
        self,
        *,
        weight_universe,
        weight_vol_lookback=30,
        regime_mode="binary",
        regime_benchmark="BTCUSDT",
        regime_ma_window=200,
        regime_ma_fast=None,
        regime_band=0.0,
        chop_exposure=0.5,
        vol_target=None,
        vol_lookback=30,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._base_risk_degree = self.risk_degree
        self.weight_universe = list(weight_universe)
        self.weight_vol_lookback = weight_vol_lookback
        self.regime_mode = regime_mode
        self.regime_benchmark = regime_benchmark
        self.regime_ma_window = regime_ma_window
        self.regime_ma_fast = regime_ma_fast
        self.regime_band = regime_band
        self.chop_exposure = chop_exposure
        self.vol_target = vol_target
        self.vol_lookback = vol_lookback
        self._exposure = self._build_exposure()
        self._vol_panel = self._build_vol_panel()

    def _build_exposure(self) -> pd.Series:
        from qlib.data import D

        close = D.features([self.regime_benchmark], ["$close"], freq="day")["$close"].droplevel(0)
        return regime_exposure_series(
            close,
            mode=self.regime_mode,
            ma_window=self.regime_ma_window,
            ma_fast=self.regime_ma_fast,
            band=self.regime_band,
            chop_exposure=self.chop_exposure,
            vol_target=self.vol_target,
            vol_lookback=self.vol_lookback,
        )

    def _build_vol_panel(self) -> pd.DataFrame:
        from qlib.data import D

        close = D.features(self.weight_universe, ["$close"], freq="day")["$close"]
        wide = close.unstack(level="instrument").sort_index()
        # Trailing realized vol per name (rolling std of daily returns). Each row d uses closes <= d.
        return wide.pct_change().rolling(self.weight_vol_lookback).std()

    def _mult_for(self, date) -> float:
        date = pd.Timestamp(date).normalize()
        exp = self._exposure
        if date in exp.index:
            return float(exp.loc[date])
        prior = exp.loc[:date]
        return float(prior.iloc[-1]) if len(prior) else 1.0

    def get_risk_degree(self, trade_step=None):
        step = trade_step if trade_step is not None else self.trade_calendar.get_trade_step()
        _, date = self.trade_calendar.get_step_time(step)
        return self._base_risk_degree * self._mult_for(date)

    def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
        names = list(score.index)
        t = pd.Timestamp(trade_start_time).normalize()
        vp = self._vol_panel
        prior = vp.loc[vp.index < t]  # NO LOOK-AHEAD: strictly-prior vol row only
        vols = prior.iloc[-1].reindex(names) if len(prior) else pd.Series(index=names, dtype="float64")
        w = inverse_vol_weights(vols)
        return {k: float(v) for k, v in w.items() if v > 0}
