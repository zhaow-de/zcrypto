"""Pure funding-rate (carry) feature computation + a qlib Processor that appends it.

Mirrors cli/experiment/features/cross_asset.py: a qlib-free pure function over a wide
`$funding` panel, plus a Processor that loads the panel via D.features and appends the
features as ("feature", <name>) columns. Features capture the perpetual-funding carry that
OHLCV lacks: level (daily carry), extremity (z vs own history), relative crowding
(cross-sectional rank), persistent regime (rolling mean), and trend (change). All are
leak-safe — current/past funding or the same-day cross-section only.
"""

from __future__ import annotations

import pandas as pd
from qlib.data.dataset.processor import Processor


def _stack(wide: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """Stack a wide (date × instrument) frame into a ("datetime","instrument") single-col frame.

    Mirrors cross_asset._stack; future_stack=True (pandas 2.1+) never silently drops NaN rows.
    """
    s = wide.stack(future_stack=True)
    s.index.names = ["datetime", "instrument"]
    return s.rename(col_name).to_frame()


def funding_features(
    funding: pd.DataFrame,
    *,
    z_window: int = 30,
    ma_window: int = 7,
    chg_window: int = 7,
) -> pd.DataFrame:
    """Map a wide daily-`$funding` panel (index=date, columns=instrument) to a
    (datetime, instrument) feature frame with the 5 focused carry columns.

    Leak-safe: every column uses only current/past funding (trailing rolling/shift) or the
    same-day cross-section (rank). Index names are exactly ("datetime", "instrument").
    """
    mean = funding.rolling(z_window).mean()
    std = funding.rolling(z_window).std()
    families = [
        _stack(funding, "funding_level"),
        _stack((funding - mean) / std, "funding_z"),
        _stack(funding.rank(axis=1, pct=True), "funding_csrank"),
        _stack(funding.rolling(ma_window).mean(), "funding_ma"),
        _stack(funding - funding.shift(chg_window), "funding_chg"),
    ]
    out = pd.concat(families, axis=1)
    out.index.names = ["datetime", "instrument"]
    return out


def _load_funding(insts, start, end) -> pd.DataFrame:
    """Load `$funding` for `insts` over [start, end] as a wide date × instrument panel.

    Thin seam over qlib's `D.features` so the processor can be tested without qlib init / redis.
    """
    from qlib.data import D

    s = D.features(list(insts), ["$funding"], start_time=start, end_time=end, freq="day")["$funding"]
    return s.unstack(level="instrument")


class FundingRateProcessor(Processor):
    """qlib `Processor` appending `funding_features` as `("feature", <name>)` columns.

    Wire it FIRST in a recipe's `infer_processors` so a later `RobustZScoreNorm` normalizes the
    appended features. `kwargs` are forwarded to `funding_features`.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, df: pd.DataFrame) -> pd.DataFrame:
        dt = df.index.get_level_values("datetime")
        insts = df.index.get_level_values("instrument").unique()
        funding = _load_funding(insts, dt.min(), dt.max())
        feats = funding_features(funding, **self.kwargs)
        feats = feats.reindex(df.index)
        for name in feats.columns:
            df[("feature", name)] = feats[name]
        return df
