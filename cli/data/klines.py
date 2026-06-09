from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Iterable

import pandas as pd

_RAW_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def parse_kline_zip(zip_bytes: bytes, symbol: str, interval: str, date: dt.date) -> pd.DataFrame:
    """Decode one Binance daily kline zip → single-row DataFrame with normalized 11 fields + date."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"{symbol} {date}: expected exactly one file in zip, got {names}")
        csv_bytes = zf.read(names[0])

    # Header detection: try first cell as int. Recent files may carry a header.
    first_cell = csv_bytes.split(b",", 1)[0].split(b"\n", 1)[0].strip()
    skiprows = 0 if first_cell.lstrip(b"-").isdigit() else 1
    df = pd.read_csv(io.BytesIO(csv_bytes), header=None, skiprows=skiprows, names=_RAW_COLS)

    if len(df) != 1:
        raise ValueError(f"{symbol} {date}: expected 1 row in kline csv, got {len(df)}")

    row = df.iloc[0]
    obs = dt.datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=dt.timezone.utc).date()
    if obs != date:
        raise ValueError(f"{symbol} {date}: kline open_time maps to {obs}, mismatch")

    volume = float(row["volume"])
    amount = float(row["quote_asset_volume"])
    close = float(row["close"])
    vwap = amount / volume if volume != 0.0 else close

    return pd.DataFrame(
        [
            {
                "date": obs,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": close,
                "volume": volume,
                "amount": amount,
                "trades": float(row["count"]),
                "taker_buy_base": float(row["taker_buy_base_volume"]),
                "taker_buy_amount": float(row["taker_buy_quote_volume"]),
                "vwap": vwap,
                "factor": 1.0,
            }
        ]
    )


def assert_no_internal_gaps(observed: Iterable[dt.date], expected: Iterable[dt.date]) -> None:
    """Raise if any expected date is missing from observed (set-difference)."""
    obs = set(observed)
    missing = [d for d in expected if d not in obs]
    if missing:
        raise ValueError(f"internal gap in fetched kline sequence; missing: {missing[:5]}")
