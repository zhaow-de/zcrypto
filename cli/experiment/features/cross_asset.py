"""Pure cross-asset feature computation — no qlib import.

Computes features that Alpha158 structurally lacks: relative strength vs BTC,
rolling beta to BTC, BTC lead-lag correlation, cointegration-deviation z-score,
and cross-sectional rank of momentum and volatility.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cross_asset_features(
    close: pd.DataFrame,
    *,
    btc: str = "BTCUSDT",
    rs_windows: tuple[int, ...] = (5, 20),
    beta_windows: tuple[int, ...] = (20, 60),
    leadlag_lags: tuple[int, ...] = (1, 2, 3),
    coint_window: int = 60,
    vol_window: int = 20,
    mom_window: int = 20,
) -> pd.DataFrame:
    """Map a wide close panel to a (datetime, instrument)-indexed cross-asset feature frame.

    Parameters
    ----------
    close:
        Wide panel — index=date, columns=instrument, values=raw close prices.
    btc:
        Column name of the BTC series used as the cross-asset reference.
    rs_windows:
        Look-back windows (days) for relative-strength features.
    beta_windows:
        Rolling windows (days) for beta-to-BTC features.
    leadlag_lags:
        Lag values (days) for BTC lead-lag correlation features.
    coint_window:
        Rolling window (days) for cointegration z-score and lead-lag correlation.
    vol_window:
        Rolling window (days) for cross-sectional volatility rank.
    mom_window:
        Look-back window (days) for cross-sectional momentum rank.

    Returns
    -------
    pd.DataFrame
        MultiIndex (datetime, instrument) frame with one column per feature.
        BTC's own rows carry neutral values: rs_*=0, beta_*=1, coint_z=0.
        Index names are exactly ("datetime", "instrument").
    """
    close = close.copy()
    rets = close.pct_change()
    btc_ret = rets[btc]

    families: list[pd.DataFrame] = []

    # --- relative strength ---------------------------------------------------
    for w in rs_windows:
        wide = (close / close.shift(w) - 1).sub(close[btc] / close[btc].shift(w) - 1, axis=0)
        wide[btc] = 0.0
        families.append(_stack(wide, f"rs_{w}"))

    # --- rolling beta to BTC -------------------------------------------------
    for w in beta_windows:
        btc_var = btc_ret.rolling(w).var()
        wide = rets.rolling(w).cov(btc_ret).div(btc_var, axis=0)
        wide[btc] = 1.0
        families.append(_stack(wide, f"beta_{w}"))

    # --- BTC lead-lag correlation ---------------------------------------------
    for lag in leadlag_lags:
        wide = rets.rolling(coint_window).corr(btc_ret.shift(lag))
        # BTC vs itself shifted: undefined — keep NaN; future_stack=True preserves NaN rows
        wide[btc] = np.nan
        families.append(_stack(wide, f"leadlag_{lag}"))

    # --- cointegration z-score -----------------------------------------------
    spread = np.log(close).sub(np.log(close[btc]), axis=0)
    coint_z = (spread - spread.rolling(coint_window).mean()) / spread.rolling(coint_window).std()
    coint_z[btc] = 0.0
    families.append(_stack(coint_z, "coint_z"))

    # --- cross-sectional rank of momentum ------------------------------------
    mom = close / close.shift(mom_window) - 1
    csrank_mom = mom.rank(axis=1, pct=True)
    families.append(_stack(csrank_mom, "csrank_mom"))

    # --- cross-sectional rank of volatility ----------------------------------
    vol = rets.rolling(vol_window).std()
    csrank_vol = vol.rank(axis=1, pct=True)
    families.append(_stack(csrank_vol, "csrank_vol"))

    result = pd.concat(families, axis=1)
    result.index.names = ["datetime", "instrument"]
    return result


def _stack(wide: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """Stack a wide (date × instrument) frame into a (datetime, instrument) Series, then wrap.

    Uses future_stack=True (pandas 2.1+) which never silently drops NaN rows.
    """
    s = wide.stack(future_stack=True)
    s.index.names = ["datetime", "instrument"]
    return s.rename(col_name).to_frame()
