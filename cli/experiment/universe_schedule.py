"""Universe schedule computation — offline, pure-pandas.

Computes a monthly (or arbitrary-frequency) top-N-by-liquidity universe schedule
from a wide daily dollar-volume panel. PIT-safe: a symbol ranks out automatically
until its trailing mean is non-NaN.
"""

from __future__ import annotations

import pandas as pd


def liquidity_rank_schedule(
    amount_wide: pd.DataFrame,
    *,
    top_n: int = 10,
    lookback_days: int,
    rebalance: str = "MS",
) -> dict[pd.Timestamp, list[str]]:
    """Compute a trailing-mean top-N universe schedule from a wide dollar-volume panel.

    Parameters
    ----------
    amount_wide:
        Wide DataFrame — index=date, columns=instrument symbols, values=$amount
        (daily quote dollar-volume). NaN where a name was not yet listed/traded.
    top_n:
        Number of names to include at each rebalance date.
    lookback_days:
        Rolling window (calendar days) for the trailing mean used to rank names.
        Uses ``min_periods=1`` so newly-listed names get credit as soon as they
        have at least one non-NaN observation within the window.
    rebalance:
        Pandas offset alias for rebalance dates (default ``"MS"`` = month-start).

    Returns
    -------
    dict[pd.Timestamp, list[str]]
        Mapping from each rebalance timestamp to the ordered list of symbols
        (best first, i.e. descending trailing mean).  Tie-break is alphabetical
        by symbol name (stable, deterministic).
    """
    # Trailing rolling mean — min_periods=1 so a name with one day of data gets a mean,
    # but a fully-NaN window stays NaN, preserving PIT eligibility.
    rolling_mean = amount_wide.rolling(window=lookback_days, min_periods=1).mean()

    # Rebalance dates within the index span
    rebalance_dates = pd.date_range(
        start=amount_wide.index.min(),
        end=amount_wide.index.max(),
        freq=rebalance,
    )

    schedule: dict[pd.Timestamp, list[str]] = {}
    for ts in rebalance_dates:
        # Align to the nearest available date on or before ts
        idx_pos = amount_wide.index.searchsorted(ts, side="right") - 1
        if idx_pos < 0:
            continue
        actual_date = amount_wide.index[idx_pos]
        row = rolling_mean.loc[actual_date].dropna()

        if row.empty:
            schedule[ts] = []
            continue

        # Sort: descending value, then ascending name for deterministic tie-break
        ranked = row.sort_values(ascending=False)
        # Stable tie-break: for equal values sort by name
        ranked = ranked.reset_index()
        ranked.columns = ["symbol", "value"]
        ranked = ranked.sort_values(["value", "symbol"], ascending=[False, True])

        top = ranked.head(top_n)["symbol"].tolist()
        schedule[ts] = top

    return schedule


def build_liquidity_schedule(
    universe,
    data_dir,
    *,
    top_n: int = 10,
    lookback_days: int,
    rebalance: str = "MS",
) -> dict[pd.Timestamp, list[str]]:
    """Load $amount from qlib and compute the liquidity-rank universe schedule.

    Parameters
    ----------
    universe:
        Iterable of instrument names to load from qlib.
    data_dir:
        Path to the qlib data directory (used for qlib initialisation upstream;
        this function assumes qlib is already initialised by the caller).
    top_n:
        Number of names per rebalance date.
    lookback_days:
        Rolling-mean window in calendar days.
    rebalance:
        Rebalance frequency alias (default ``"MS"``).

    Returns
    -------
    dict[pd.Timestamp, list[str]]
        Same shape as ``liquidity_rank_schedule``.
    """
    from qlib.data import D

    df = D.features(list(universe), ["$amount"], freq="day")
    # df is a MultiIndex (datetime, instrument) DataFrame with column "$amount"
    amount_wide = df["$amount"].unstack(level="instrument").sort_index()
    return liquidity_rank_schedule(amount_wide, top_n=top_n, lookback_days=lookback_days, rebalance=rebalance)
