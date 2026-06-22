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
        membership_top_n: int | None = None,
        membership_lookback_days: int | None = None,
        trend_window: int | None = None,
        compose_market_gate: bool = False,
        froth_field: str | None = None,
        froth_lookback: int = 90,
        froth_z_threshold: float = 1.5,
        froth_derisk_mult: float = 0.0,
        crowding_field: str | None = None,
        crowding_tilt_k: float = 1.0,
        oi_divergence: bool = False,
        oi_div_lookback: int = 14,
        oi_div_tilt_k: float = 1.0,
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
        self.membership_top_n = membership_top_n
        self.membership_lookback_days = membership_lookback_days
        self.trend_window = trend_window
        self.compose_market_gate = compose_market_gate
        self.froth_field = froth_field
        self.froth_lookback = froth_lookback
        self.froth_z_threshold = froth_z_threshold
        self.froth_derisk_mult = froth_derisk_mult
        self.crowding_field = crowding_field
        self.crowding_tilt_k = crowding_tilt_k
        self.oi_divergence = oi_divergence
        self.oi_div_lookback = oi_div_lookback
        self.oi_div_tilt_k = oi_div_tilt_k
        self._membership_schedule: dict | None = None  # lazy; injectable for tests
        self._close_panel: pd.DataFrame | None = None  # lazy; injectable for tests
        self._froth_signal: pd.Series | None = None  # lazy; injectable for tests
        self._crowding_panel: pd.DataFrame | None = None  # lazy; injectable for tests
        self._oi_div_signal: pd.DataFrame | None = None  # lazy; injectable for tests
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

    def _build_close_panel(self) -> pd.DataFrame:
        """Lazily fetch the per-asset close panel (wide: date × instrument)."""
        from qlib.data import D

        close = D.features(self.weight_universe, ["$close"], freq="day")["$close"]
        return close.unstack(level="instrument").sort_index()

    def _build_froth_signal(self) -> pd.Series:
        """Cross-sectional median basis z-score over the weight universe.

        Reads ``froth_field`` from D.features, takes the per-date median across instruments,
        and computes a rolling z-score over ``froth_lookback`` days.  Each row d uses only
        dates ≤ d (rolling window, no look-ahead).  Returns a date-indexed Series of z-scores.
        """
        from qlib.data import D

        raw = D.features(self.weight_universe, [self.froth_field], freq="day")[self.froth_field]
        wide = raw.unstack(level="instrument").sort_index()  # date × instrument
        cs_median = wide.median(axis=1)  # cross-sectional median per date
        lb = getattr(self, "froth_lookback", 90)
        roll_mean = cs_median.rolling(lb, min_periods=lb).mean()
        roll_std = cs_median.rolling(lb, min_periods=lb).std()
        return (cs_median - roll_mean) / roll_std  # rolling z-score; early rows → NaN

    def _build_crowding_panel(self) -> pd.DataFrame:
        """Lazily fetch the per-asset crowding-field panel (wide: date × instrument)."""
        from qlib.data import D

        raw = D.features(self.weight_universe, [self.crowding_field], freq="day")[self.crowding_field]
        return raw.unstack(level="instrument").sort_index()

    def _build_oi_div_signal(self) -> pd.DataFrame:
        """Build the OI-price-divergence confirmation panel (wide: date × instrument).

        Per coin: confirmation = sign(price_chg) * oi_chg, where price_chg and oi_chg are
        the L-day fractional change (L = oi_div_lookback).  Positive = confirmed (price↑+OI↑
        or price↓+OI↓); negative = divergent (price↑+OI↓ or price↓+OI↑).  NaN where $oi is
        NaN (no perp data / warmup period).
        """
        from qlib.data import D

        df = D.features(self.weight_universe, ["$close", "$oi"], freq="day")
        close_wide = df["$close"].unstack(level="instrument").sort_index()
        oi_wide = df["$oi"].unstack(level="instrument").sort_index()
        L = getattr(self, "oi_div_lookback", 14)
        price_chg = close_wide / close_wide.shift(L) - 1
        oi_chg = oi_wide / oi_wide.shift(L) - 1
        # confirmation = sign(price_chg) * oi_chg; NaN where oi is NaN (or within warmup)
        return np.sign(price_chg) * oi_chg

    @staticmethod
    def _apply_cross_sectional_tilt(w: pd.Series, signal_row: pd.Series, k: float, sign: float) -> pd.Series:
        """Apply a multiplicative cross-sectional tilt to weights.

        z-scores ``signal_row`` across the names in ``w``; applies ``exp(sign * k * z)`` as a
        multiplicative tilt; NaN signal → neutral tilt 1.0; renormalizes the result.
        Returns ``w`` unchanged if fewer than 2 valid signal values or std is 0.
        """
        row = signal_row.reindex(w.index)
        valid = row.dropna()
        if len(valid) < 2:
            return w
        std = valid.std(ddof=0)
        if std == 0:
            return w
        z = (row - valid.mean()) / std  # NaN for names not in valid stays NaN
        tilt = np.exp(sign * k * z).fillna(1.0)  # NaN signal → neutral tilt 1.0
        w = w * tilt
        total = w.sum()
        if total > 0:
            w = w / total
        return w

    def _mult_for(self, date) -> float:
        # Per-asset trend replace mode: disable the market BTC gate; the per-asset filter governs.
        # In compose mode (compose_market_gate=True), the gate stays active alongside the per-asset filter.
        if getattr(self, "trend_window", None) is not None and not getattr(self, "compose_market_gate", False):
            m = 1.0
        else:
            date_ts = pd.Timestamp(date).normalize()
            exp = self._exposure
            if date_ts in exp.index:
                m = float(exp.loc[date_ts])
            else:
                prior = exp.loc[:date_ts]
                m = float(prior.iloc[-1]) if len(prior) else 1.0

        # Basis-froth overlay: if froth_z > threshold → de-risk by froth_derisk_mult.
        if getattr(self, "froth_field", None) is not None:
            # Lazily build (or use injected) froth signal.
            if self._froth_signal is None:
                self._froth_signal = self._build_froth_signal()
            froth_z_series = self._froth_signal
            date_ts = pd.Timestamp(date).normalize()
            # Carry-forward: use the latest value ≤ date (same convention as _exposure lookup).
            prior_froth = froth_z_series.loc[froth_z_series.index <= date_ts]
            if len(prior_froth):
                z = prior_froth.iloc[-1]
                threshold = getattr(self, "froth_z_threshold", 1.5)
                derisk_mult = getattr(self, "froth_derisk_mult", 0.0)
                if not (z != z) and z > threshold:  # NaN check: NaN != NaN is True
                    m *= derisk_mult

        return m

    def _members_for(self, date) -> set[str] | None:
        """Return the set of liquidity-member symbols for *date*, or None if no filter is set."""
        if self.membership_top_n is None:
            return None
        # Lazily build the schedule on first call (unless injected for testing).
        if self._membership_schedule is None:
            from qlib.data import D

            from cli.experiment.universe_schedule import liquidity_rank_schedule

            df = D.features(self.weight_universe, ["$amount"], freq="day")
            amount_wide = df["$amount"].unstack(level="instrument").sort_index()
            self._membership_schedule = liquidity_rank_schedule(
                amount_wide,
                top_n=self.membership_top_n,
                lookback_days=self.membership_lookback_days,
            )
        schedule = self._membership_schedule
        # Normalize to month-start, then exact-or-carry-forward most recent prior rebalance.
        t = pd.Timestamp(date).normalize().to_period("M").to_timestamp()
        keys = sorted(k for k in schedule if k <= t)
        if not keys:
            return None  # before first rebalance -> no restriction
        return set(schedule[keys[-1]])

    def get_risk_degree(self, trade_step=None):
        step = trade_step if trade_step is not None else self.trade_calendar.get_trade_step()
        _, date = self.trade_calendar.get_step_time(step)
        return self._base_risk_degree * self._mult_for(date)

    def _trend_above_sma(self, names: list[str], trade_date) -> list[str]:
        """Return the subset of *names* whose close at *trade_date* is strictly above
        their own ``trend_window``-day SMA. Uses data on/before *trade_date* only (no look-ahead).
        """
        tw = getattr(self, "trend_window", None)
        if tw is None:
            return names
        t = pd.Timestamp(trade_date).normalize()
        # Build/fetch the close panel (injectable seam for tests).
        if self._close_panel is None:
            self._close_panel = self._build_close_panel()
        cp = self._close_panel
        # Restrict to on-or-before trade date (no look-ahead).
        cp_prior = cp.loc[cp.index <= t]
        if len(cp_prior) < tw:
            return names  # insufficient history -> no filtering (matches warmup convention)
        sma = cp_prior.rolling(tw).mean().iloc[-1]  # SMA row at (or just before) trade date
        last_close = cp_prior.iloc[-1]  # close at (or most recent before) trade date
        return [n for n in names if n in last_close.index and last_close[n] > sma.get(n, float("nan"))]

    def generate_target_weight_position(self, score, current, trade_start_time, trade_end_time):
        names = list(score.index)
        if getattr(self, "membership_top_n", None) is not None:
            members = self._members_for(trade_start_time)
            if members is not None:
                names = [n for n in names if n in members]
        # Per-asset trend filter: drop names whose close is ≤ their own SMA(trend_window).
        if getattr(self, "trend_window", None) is not None:
            names = self._trend_above_sma(names, trade_start_time)
        t = pd.Timestamp(trade_start_time).normalize()
        vp = self._vol_panel
        prior = vp.loc[vp.index < t]  # NO LOOK-AHEAD: strictly-prior vol row only
        vols = prior.iloc[-1].reindex(names) if len(prior) else pd.Series(index=names, dtype="float64")
        w = inverse_vol_weights(vols)
        # Crowding tilt: down-weight high-basis coins (−k sign → exp(−k*z)).
        if getattr(self, "crowding_field", None) is not None and len(w) > 0:
            # Lazily build (or use injected) crowding panel.
            if self._crowding_panel is None:
                self._crowding_panel = self._build_crowding_panel()
            cp = self._crowding_panel
            cp_prior = cp.loc[cp.index < t]  # STRICTLY prior — same discipline as vol lookup
            if len(cp_prior) > 0:
                row = cp_prior.iloc[-1]
                k = getattr(self, "crowding_tilt_k", 1.0)
                w = self._apply_cross_sectional_tilt(w, row, k, sign=-1.0)
        # OI-divergence tilt: up-weight confirmed-trend coins (+k sign → exp(+k*z)).
        if getattr(self, "oi_divergence", False) and len(w) > 0:
            # Lazily build (or use injected) OI-divergence signal panel.
            if self._oi_div_signal is None:
                self._oi_div_signal = self._build_oi_div_signal()
            op = self._oi_div_signal
            op_prior = op.loc[op.index < t]  # STRICTLY prior — no look-ahead
            if len(op_prior) > 0:
                row = op_prior.iloc[-1]
                k = getattr(self, "oi_div_tilt_k", 1.0)
                w = self._apply_cross_sectional_tilt(w, row, k, sign=+1.0)
        return {k: float(v) for k, v in w.items() if v > 0}
