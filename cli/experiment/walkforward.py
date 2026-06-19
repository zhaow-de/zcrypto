"""Pure walk-forward period splitter — no qlib dependency."""

from __future__ import annotations

import pandas as pd


def build_wf_periods(
    train_start: str,
    test_start: str,
    test_end: str,
    *,
    freq: str = "quarter",
    window: str = "expanding",
    rolling_years: int = 3,
    purge_days: int = 0,
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Split the holdout window into walk-forward retrain periods.

    Parameters
    ----------
    train_start:
        Earliest date of training data (ISO YYYY-MM-DD).
    test_start:
        First date of the holdout / predict window (inclusive).
    test_end:
        Last date of the holdout / predict window (inclusive, clamped).
    freq:
        Granularity of each period — ``"quarter"`` or ``"year"``.
    window:
        ``"expanding"`` keeps train_start fixed; ``"rolling"`` sets
        train_start = predict_start − rolling_years.
    rolling_years:
        Look-back length for rolling window (ignored when expanding).
    purge_days:
        Gap days between train_end and predict_start.
        train_end = predict_start − (purge_days + 1).

    Returns
    -------
    list of ((train_start, train_end), (predict_start, predict_end))
        All dates as ISO ``YYYY-MM-DD`` strings.
    """
    ts_start = pd.Timestamp(test_start)
    ts_end = pd.Timestamp(test_end)

    # Build the sequence of predict periods by iterating calendar periods.
    pd_freq = "Q" if freq == "quarter" else "Y"
    first_period = pd.Period(ts_start, freq=pd_freq)
    last_period = pd.Period(ts_end, freq=pd_freq)

    periods: list[tuple[tuple[str, str], tuple[str, str]]] = []
    p = first_period
    while p <= last_period:
        predict_start = max(pd.Timestamp(p.start_time.date()), ts_start)
        predict_end_raw = pd.Timestamp(p.end_time.date())
        predict_end = min(predict_end_raw, ts_end)

        gap = pd.Timedelta(days=purge_days + 1)
        train_end = predict_start - gap

        if window == "rolling":
            eff_train_start = predict_start - pd.DateOffset(years=rolling_years)
        else:
            eff_train_start = pd.Timestamp(train_start)

        periods.append(
            (
                (eff_train_start.strftime("%Y-%m-%d"), train_end.strftime("%Y-%m-%d")),
                (predict_start.strftime("%Y-%m-%d"), predict_end.strftime("%Y-%m-%d")),
            )
        )
        p += 1

    return periods
