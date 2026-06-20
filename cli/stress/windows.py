"""Out-of-sample walk-forward window grid for `zcrypto stress` (see docs/specs/00021).

Each window trains only on data strictly before its test period (expanding from data_start),
with a purge gap >= the label horizon so the forward-looking label cannot leak train -> test.
Pure / qlib-free so the leak-safe window math is unit-testable in isolation.
"""

from __future__ import annotations

import datetime as dt

PURGE_DAYS: int = 8  # >= label_horizon_days (6); the gap between train_end and test_start


def build_oos_windows(
    test_starts: list[str],
    *,
    data_start: str,
    data_end: str,
    purge_days: int = PURGE_DAYS,
) -> list[dict]:
    """Build OOS walk-forward windows from annual test-start dates.

    For each `test_start`: train = [data_start, test_start - purge_days]; test = [test_start,
    (next test_start - 1 day) or data_end for the last]; valid = the purge gap (ignored by the
    multi-seed light holdout, kept well-formed). Returns one dict per window in order.
    """
    starts = sorted(test_starts)
    windows: list[dict] = []
    for i, ts in enumerate(starts):
        ts_d = dt.date.fromisoformat(ts)
        train_end = ts_d - dt.timedelta(days=purge_days)
        if i + 1 < len(starts):
            test_end = dt.date.fromisoformat(starts[i + 1]) - dt.timedelta(days=1)
        else:
            test_end = dt.date.fromisoformat(data_end)
        windows.append(
            {
                "label": f"oos_{ts_d.year}",
                "train": (data_start, train_end.isoformat()),
                "valid": ((train_end + dt.timedelta(days=1)).isoformat(), (ts_d - dt.timedelta(days=1)).isoformat()),
                "test": (ts, test_end.isoformat()),
            }
        )
    return windows
