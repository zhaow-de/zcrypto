"""Market-neutral long/short quantile-spread evaluator (see docs/specs/00020).

qlib's SimulatorExecutor cannot short, so a cross-sectional signal's monetizable form — the
long-short quantile spread — is computed directly from the model's prediction scores + the
realized forward returns. Per date: long the top-k by score, short the bottom-k (equal weight,
dollar-neutral); the daily spread is `mean(long fwd) - mean(short fwd)`, net of realistic
per-side turnover costs. Pure (no qlib.init / D.features) so it is unit-testable in isolation.
"""

from __future__ import annotations

import pandas as pd


def long_short_spread(
    scores: pd.Series,
    fwd_returns: pd.Series,
    *,
    k: int = 5,
    cost_per_side: float = 0.0,
) -> dict:
    """Daily dollar-neutral long-top-k / short-bottom-k spread, net of turnover cost.

    `scores` / `fwd_returns` are (datetime, instrument)-indexed Series. Returns
    {"daily": Series, "sharpe": float, "ending": float}.
    """
    df = pd.DataFrame({"score": scores, "fwd": fwd_returns}).dropna()
    daily: dict = {}
    prev_long: set = set()
    prev_short: set = set()
    for dt, g in df.groupby(level="datetime"):
        n = len(g)
        kk = min(k, n // 2)
        if kk < 1:
            daily[dt] = 0.0
            prev_long, prev_short = set(), set()
            continue
        g = g.sort_values("score")
        shorts = g.head(kk)
        longs = g.tail(kk)
        spread = float(longs["fwd"].mean() - shorts["fwd"].mean())
        long_set = set(longs.index.get_level_values("instrument"))
        short_set = set(shorts.index.get_level_values("instrument"))
        turnover = len(long_set - prev_long) / kk + len(short_set - prev_short) / kk
        daily[dt] = spread - cost_per_side * turnover
        prev_long, prev_short = long_set, short_set

    s = pd.Series(daily).sort_index()
    sharpe = _sharpe(s)
    ending = float((1.0 + s).prod())
    return {"daily": s, "sharpe": sharpe, "ending": ending}


def _sharpe(net: pd.Series) -> float:
    """Annualized information ratio of the daily net series (qlib's risk_analysis definition).

    Matches the long-only holdout `sharpe` so the two are directly comparable. A degenerate
    zero-variance (or <2-point) series returns 0.0 — never inf/NaN, which would poison the
    cross-seed mean/std aggregation in summarize_seed_metrics (statistics.stdev raises on inf).
    """
    if len(net) < 2 or net.std() == 0:
        return 0.0
    from qlib.contrib.evaluate import risk_analysis

    ir = float(risk_analysis(net, freq="day").loc["information_ratio"].iloc[0])
    return 0.0 if ir != ir else ir  # map NaN -> 0.0
