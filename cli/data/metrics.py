"""Futures metrics decoder: OI + long-short ratios + taker ratio.

No network, no qlib — stdlib + pandas only.

RECON (verified against data.binance.vision on 2026-06-22):
  - Archive: data/futures/um/daily/metrics/<PERP>/<PERP>-metrics-<YYYY-MM-DD>.zip
  - One CSV per zip, columns (header present):
      create_time, symbol, sum_open_interest, sum_open_interest_value,
      count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
      count_long_short_ratio, sum_taker_long_short_vol_ratio
  - Granularity: 5-minute snapshots (288 rows per daily file). The spec said
    "daily-granularity only" — the archive is actually 5-minute intraday bars.
    The decoder reduces to a single daily row by taking the LAST-of-day (~23:55)
    snapshot, which aligns with $close (the daily close price) and matches the daily
    OI Binance displays (a mean would smooth away end-of-day flow info).
  - create_time is a UTC datetime string ("YYYY-MM-DD HH:MM:SS"), NOT an epoch.

Field mapping (qlib ← archive column; value = the last-of-day 23:55 snapshot):
  $oi          <- sum_open_interest              (end-of-day open interest)
  $oi_value    <- sum_open_interest_value        (end-of-day OI value, USD)
  $ls_top      <- sum_toptrader_long_short_ratio (top-trader position-size L/S ratio)
  $ls_global   <- count_long_short_ratio         (global account-based L/S ratio)
  $taker_ratio <- sum_taker_long_short_vol_ratio (taker buy/sell volume ratio)

Note: Binance column names are misleading — "count_*" fields are ratios, not counts;
"sum_*" fields are ratios, not sums. The names are as published by data.binance.vision.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pandas as pd

_REQUIRED_COLS = [
    "sum_open_interest",
    "sum_open_interest_value",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
]

_FIELD_MAP = {
    "sum_open_interest": "$oi",
    "sum_open_interest_value": "$oi_value",
    "sum_toptrader_long_short_ratio": "$ls_top",
    "count_long_short_ratio": "$ls_global",
    "sum_taker_long_short_vol_ratio": "$taker_ratio",
}


def parse_metrics_zip(zip_bytes: bytes, perp: str, date: dt.date) -> pd.DataFrame:  # noqa: ARG001
    """Decode one Binance daily metrics zip → single-row DataFrame with 5 normalized fields.

    The archive contains 288 5-minute intraday rows; the last-of-day (~23:55) snapshot is
    taken as the single daily row, date-indexed (close-aligned). `perp` is accepted for
    call-site symmetry but is not used in the body.

    Returns a DataFrame with columns: $oi, $oi_value, $ls_top, $ls_global, $taker_ratio.
    Index is a DatetimeIndex with a single entry at `date`.

    Raises ValueError on: multiple files in zip, missing required columns, or no data rows.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"{perp} {date}: expected exactly one file in zip, got {names}")
        csv_bytes = zf.read(names[0])

    df = pd.read_csv(io.BytesIO(csv_bytes))

    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{perp} {date}: missing column(s) in metrics CSV: {missing}")

    if len(df) == 0:
        raise ValueError(f"{perp} {date}: no data rows in metrics CSV")

    # Take the LAST-of-day (~23:55) snapshot, not the mean: it aligns with $close (the daily close
    # price) and matches Binance's displayed daily OI, and preserves end-of-day flow (taker_ratio
    # swings ~2x intraday). Both last and mean are no-look-ahead (same-day rows only).
    daily = df.sort_values("create_time")[_REQUIRED_COLS].iloc[-1]

    result = pd.DataFrame(
        [
            {
                "$oi": float(daily["sum_open_interest"]),
                "$oi_value": float(daily["sum_open_interest_value"]),
                "$ls_top": float(daily["sum_toptrader_long_short_ratio"]),
                "$ls_global": float(daily["count_long_short_ratio"]),
                "$taker_ratio": float(daily["sum_taker_long_short_vol_ratio"]),
            }
        ],
        index=pd.Index([date], name="date"),
    )
    return result
