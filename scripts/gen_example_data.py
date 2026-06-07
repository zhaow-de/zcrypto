"""Dev-only one-off: fetch daily crypto OHLCV via yfinance into the bundled CSV.

Run: uv run --with yfinance python scripts/gen_example_data.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

from cli.example.config import INSTRUMENTS, WINDOW

YAHOO = {code: f"{code[:-3]}-USD" for code in INSTRUMENTS}  # BTCUSD -> BTC-USD
OUT = Path(__file__).resolve().parents[1] / "cli" / "example" / "data" / "crypto_ohlcv.csv.gz"


def _fetch(code: str) -> pd.DataFrame:
    start, end = WINDOW
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(
        YAHOO[code],
        start=start,
        end=end_excl,
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    d = raw.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
    d.columns = ["date", "open", "high", "low", "close", "volume"]
    d["symbol"] = code
    return d


def main() -> None:
    frames = [_fetch(code) for code in INSTRUMENTS]
    common = set.intersection(*(set(f["date"]) for f in frames))
    df = pd.concat(frames)
    df = df[df["date"].isin(common)].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["symbol", "date"])[["date", "symbol", "open", "high", "low", "close", "volume"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, compression="gzip")
    print(f"wrote {OUT} ({len(df)} rows, {df['symbol'].nunique()} symbols, {df['date'].nunique()} dates)")


if __name__ == "__main__":
    main()
