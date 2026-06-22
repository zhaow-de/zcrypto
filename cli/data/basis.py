"""Perp-spot basis decoder: premium index close.

No network, no qlib — stdlib + pandas only.

RECON (verified against data.binance.vision on 2026-06-22):
  - Archive: data/futures/um/daily/premiumIndexKlines/<PERP>/1d/<PERP>-1d-<YYYY-MM-DD>.zip
  - One CSV per zip, OHLC kline schema (no header quote marks), columns:
      open_time, open, high, low, close, volume, close_time,
      quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore
  - Granularity: true daily (one 1d candle per daily archive file).
    Each zip contains exactly one row — the full-day 1d candle.
  - open_time and close_time are epoch milliseconds (NOT UTC strings).

Field mapping:
  $basis <- close  (the premium index daily close)

$basis definition:
  The Binance premium index measures the perp's premium over the underlying index price.
  The daily close of this index (the last value on the UTC day) is used as $basis.
  It is already expressed as a fraction (e.g. 0.00070818 ≈ +0.07% perp premium over index).
  Negative values indicate a perp discount (contango/backwardation).

  This is Candidate A from the probe: premiumIndexKlines 1d close — one archive, directly
  the premium index, no arithmetic across multiple sources.
  URL confirmed: futures/um/daily/premiumIndexKlines/<PERP>/1d/<PERP>-1d-<YYYY-MM-DD>.zip
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pandas as pd

# Positional column names for the 12-column kline schema (headerless archives).
# Older premiumIndexKlines archives (pre-~2021) omit the header row; recent ones include it.
# Either way, $basis = close (index 4).
_KLINE_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def parse_basis_zip(zip_bytes: bytes, perp: str, date: dt.date) -> pd.DataFrame:  # noqa: ARG001
    """Decode one Binance daily premiumIndexKlines zip → single-row DataFrame with $basis.

    The archive contains exactly one 1d OHLC candle row. The `close` column (index 4) is
    taken as the daily $basis (the premium index close, a fraction). `perp` is accepted for
    call-site symmetry but is not used in the body.

    Handles BOTH archive formats:
    - Headered (recent archives, e.g. 2024-08-16): first row is the column-name header.
    - Headerless (older archives, e.g. 2020-07-16): raw positional kline values, no header.

    Returns a DataFrame with one column ($basis) and a single-entry DatetimeIndex at `date`.

    Raises ValueError on: multiple files in zip, missing 'close' column, or no data rows.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"{perp} {date}: expected exactly one file in zip, got {names}")
        csv_bytes = zf.read(names[0])

    # Read without assuming a header so both formats are handled uniformly.
    df = pd.read_csv(io.BytesIO(csv_bytes), header=None)

    # Detect a header row: if the first cell is non-numeric (e.g. "open_time"), drop it.
    try:
        float(df.iloc[0, 0])
        has_header = False
    except (ValueError, TypeError):
        has_header = True

    if has_header:
        df = df.iloc[1:].reset_index(drop=True)

    # Assign positional column names so both paths share the same accessor.
    if len(df.columns) != len(_KLINE_COLS):
        raise ValueError(f"{perp} {date}: expected {len(_KLINE_COLS)} columns in basis CSV, got {len(df.columns)}")
    df.columns = _KLINE_COLS

    if len(df) == 0:
        raise ValueError(f"{perp} {date}: no data rows in basis CSV")

    # The 1d archive has exactly one row. Take the close of that single daily candle —
    # this is the close-aligned (end-of-day) premium index value, consistent with $close alignment.
    basis_value = float(df["close"].iloc[-1])

    return pd.DataFrame(
        [{"$basis": basis_value}],
        index=pd.Index([date], name="date"),
    )
