"""Pure derivatives feature computation + a qlib Processor that appends it.

Mirrors cli/experiment/features/funding.py: qlib-free pure functions over wide per-field
panels (date × instrument), plus a Processor that loads the panels via D.features and
appends the features as ("feature", <name>) columns.

Fields: $oi, $oi_value, $ls_top, $ls_global, $taker_ratio, $basis (plus $close for
derived signals).

Per-field features (leak-safe: trailing rolling/shift or same-day cross-section only):
  - <field>_level        — raw value (level)
  - <field>_change       — percentage change vs n periods ago (x/x.shift(n) - 1)
  - <field>_csrank       — same-day cross-sectional rank (pct=True)
  - <field>_z            — z-score vs own trailing history ((x - roll_mean) / roll_std)

Derived signals flagged by single-factor sweep (iter-39–44):
  - oi_confirm           — sign(close_pct_chg) * oi_pct_chg (OI-price alignment)
  - smart_div            — $ls_top / $ls_global (smart-money vs broad-market L/S ratio)

All columns use only current/past data (trailing rolling/shift) or the same-day
cross-section (rank) — no look-ahead, exactly like funding_features. NaN where a source
field is NaN (no perp / pre-launch). Non-finite values in derived columns are replaced
with NaN (e.g. smart_div when $ls_global = 0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from qlib.data.dataset.processor import Processor

_FIELDS = ("$oi", "$oi_value", "$ls_top", "$ls_global", "$taker_ratio", "$basis")
_FIELD_NAMES = ("oi", "oi_value", "ls_top", "ls_global", "taker_ratio", "basis")


def _stack(wide: pd.DataFrame, col_name: str) -> pd.DataFrame:
    """Stack a wide (date × instrument) frame into a ("datetime","instrument") single-col frame.

    Mirrors funding._stack; future_stack=True (pandas 2.1+) never silently drops NaN rows.
    """
    s = wide.stack(future_stack=True)
    s.index.names = ["datetime", "instrument"]
    return s.rename(col_name).to_frame()


def derivatives_features(
    panels: dict[str, pd.DataFrame],
    *,
    z_window: int = 30,
    chg_window: int = 5,
) -> pd.DataFrame:
    """Map a dict of wide daily panels (index=date, columns=instrument) to a
    (datetime, instrument) feature frame.

    ``panels`` must contain keys: '$oi', '$oi_value', '$ls_top', '$ls_global',
    '$taker_ratio', '$basis', '$close'.

    Leak-safe: every column uses only current/past data (trailing rolling/shift) or the
    same-day cross-section (rank). Index names are exactly ("datetime", "instrument").
    """
    families: list[pd.DataFrame] = []

    for field, name in zip(_FIELDS, _FIELD_NAMES):
        x = panels[field]
        mean = x.rolling(z_window).mean()
        std = x.rolling(z_window).std()

        families.append(_stack(x, f"{name}_level"))
        raw_chg = x / x.shift(chg_window) - 1
        families.append(_stack(raw_chg.where(np.isfinite(raw_chg)), f"{name}_change"))
        families.append(_stack(x.rank(axis=1, pct=True), f"{name}_csrank"))
        families.append(_stack((x - mean) / std, f"{name}_z"))

    # Derived: OI-price alignment signal
    close = panels["$close"]
    oi = panels["$oi"]
    close_chg = close / close.shift(chg_window) - 1
    oi_chg = oi / oi.shift(chg_window) - 1
    oi_confirm = np.sign(close_chg) * oi_chg
    families.append(_stack(oi_confirm, "oi_confirm"))

    # Derived: smart-money vs broad L/S ratio; non-finite → NaN
    smart_div_raw = panels["$ls_top"] / panels["$ls_global"]
    smart_div = smart_div_raw.where(np.isfinite(smart_div_raw))
    families.append(_stack(smart_div, "smart_div"))

    out = pd.concat(families, axis=1)
    out.index.names = ["datetime", "instrument"]
    return out


def _load_derivatives(insts, start, end) -> dict[str, pd.DataFrame]:
    """Load all derivatives fields + $close for ``insts`` over [start, end] as wide panels.

    Thin seam over qlib's D.features so the processor can be tested without qlib init / redis.
    """
    from qlib.data import D  # pragma: no cover

    fields = list(_FIELDS) + ["$close"]  # pragma: no cover
    raw = D.features(list(insts), fields, start_time=start, end_time=end, freq="day")  # pragma: no cover
    return {f: raw[f].unstack(level="instrument") for f in fields}  # pragma: no cover


class DerivativesProcessor(Processor):
    """qlib Processor appending derivatives_features as ("feature", <name>) columns.

    Wire it FIRST in a recipe's infer_processors so a later RobustZScoreNorm normalizes
    the appended features. kwargs are forwarded to derivatives_features.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, df: pd.DataFrame) -> pd.DataFrame:
        dt = df.index.get_level_values("datetime")
        insts = df.index.get_level_values("instrument").unique()
        panels = _load_derivatives(insts, dt.min(), dt.max())
        feats = derivatives_features(panels, **self.kwargs)
        feats = feats.reindex(df.index)
        for name in feats.columns:
            df[("feature", name)] = feats[name]
        return df
