"""1h-kline fetcher-reader for the lead-lag feasibility probe (iter-51).

Probe-local parser + fetcher — does NOT touch the pipeline/qlib writer or SUPPORTED_INTERVALS.
Data lands in .tmp/ (gitignored). Run via: uv run python -m cli.research.leadlag ...

Reuses from cli/data/binance.py:
  - _pool (PoolManager, line 22): shared urllib3 connection pool
  - _retryable_request (line 150): retry/timeout/4xx policy
  - HttpStatusError (line 25): 4xx exception for 404-skip logic
  - kline_zip_url (line 67): URL builder for kline zips
  - FetchConfig defaults (fetch_concurrency=8, http_timeout_get_secs=60, http_retry_attempts=3)
"""

from __future__ import annotations

import datetime as dt
import io
import socket
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from cli.config import FetchConfig
from cli.data.binance import HttpStatusError, _pool, _retryable_request, kline_zip_url
from cli.logging import get_logger

logger = get_logger("research.leadlag.data")

# Contract columns — the hard schema Task 2 codes against.
_CONTRACT_COLS = ["timestamp_open_utc", "symbol", "open", "high", "low", "close", "volume"]

# Raw CSV column names for the 12-column Binance kline schema.
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


def _open_time_to_utc_ts(open_time: int) -> pd.Timestamp:
    """Convert a Binance kline open_time to a tz-aware UTC Timestamp, keeping the full hour.

    Mirrors _open_time_to_date in cli/data/klines.py (line 26) but keeps the hour rather than
    dropping it to a date. Per-row ms/µs auto-detection: divide by 1000 until value < 1e10
    (seconds range), then interpret as epoch seconds.
    """
    ts = open_time
    while ts >= 10_000_000_000:
        ts //= 1000
    return pd.to_datetime(ts, unit="s", utc=True)


def parse_1h_kline_zip(raw_bytes: bytes, symbol: str) -> pd.DataFrame:
    """Decode one Binance daily 1h kline zip → 24-row DataFrame with contract columns.

    Handles BOTH headered and headerless CSVs (mirrors the detection logic in klines.py line 54
    and basis.py). Per-row ms/µs unit auto-detection for open_time (mirrors _open_time_to_date).

    Returns a DataFrame with columns: timestamp_open_utc, symbol, open, high, low, close, volume.
    timestamp_open_utc is tz-aware (UTC). Does NOT assert row count == 1 (unlike parse_kline_zip).
    """
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"{symbol}: expected exactly one file in zip, got {names}")
        csv_bytes = zf.read(names[0])

    # Header detection: if the first cell is non-numeric, it's a header row — skip it.
    # Mirrors the logic in cli/data/klines.py (line 55) and cli/data/basis.py (line 79).
    first_cell = csv_bytes.split(b",", 1)[0].split(b"\n", 1)[0].strip()
    skiprows = 0 if first_cell.lstrip(b"-").isdigit() else 1

    df = pd.read_csv(io.BytesIO(csv_bytes), header=None, skiprows=skiprows, names=_RAW_COLS)

    # Per-row ms/µs auto-detection (mirrors _open_time_to_date; applied element-wise so ms
    # and µs rows within the same file — straddling the 2025-01-01 boundary — parse correctly).
    df["timestamp_open_utc"] = df["open_time"].astype(int).apply(_open_time_to_utc_ts)
    df["symbol"] = symbol

    result = df[_CONTRACT_COLS].copy()
    for col in ("open", "high", "low", "close", "volume"):
        result[col] = result[col].astype(float)

    return result


def fetch_1h_klines(
    symbols: list[str],
    start: dt.date,
    end: dt.date,
    cache_path: str = ".tmp/leadlag/1h_klines.parquet",
) -> pd.DataFrame:
    """Fetch per-day 1h kline zips for each symbol over [start, end], concat into the contract frame.

    URL pattern: data.binance.vision/data/spot/daily/klines/{SYM}/1h/{SYM}-1h-{YYYY-MM-DD}.zip
    Built via kline_zip_url (cli/data/binance.py line 67) with interval="1h".

    Concurrency: ThreadPoolExecutor with FetchConfig.fetch_concurrency (default 8), reusing
    _pool and _retryable_request from cli/data/binance.py (lines 22, 150).

    Cache: if cache_path exists, loads + returns it without fetching. Otherwise fetches, caches,
    and returns. Missing/404 days are skipped with a WARNING — not fatal.

    Returns a long/tidy DataFrame sorted by (symbol, timestamp_open_utc) with contract columns:
    ["timestamp_open_utc", "symbol", "open", "high", "low", "close", "volume"]
    timestamp_open_utc: tz-aware UTC Timestamp (bar open time, hourly)
    symbol: uppercase pair string (e.g. "BTCUSDT")
    open/high/low/close/volume: float64
    """
    cache = Path(cache_path)
    if cache.exists():
        logger.info("cache hit — loading 1h klines from %s", cache)
        df = pd.read_parquet(cache)
        return df.sort_values(["symbol", "timestamp_open_utc"]).reset_index(drop=True)

    fetch = FetchConfig()

    # Backstop: set a process-wide socket read timeout to cut a stale keep-alive ssl.read hang.
    # Mirrors BinanceSource.__init__ in cli/data/binance.py — see comment there for full rationale.
    socket.setdefaulttimeout(fetch.http_timeout_get_secs + 10)

    # Build (symbol, date) work list.
    work: list[tuple[str, dt.date]] = []
    cur = start
    while cur <= end:
        for sym in symbols:
            work.append((sym, cur))
        cur += dt.timedelta(days=1)

    logger.info(
        "fetching %d (symbol, date) 1h kline zips concurrently (max_workers=%d)",
        len(work),
        fetch.fetch_concurrency,
    )

    frames: list[pd.DataFrame] = []

    def _fetch_one(sym: str, date: dt.date) -> pd.DataFrame | None:
        url = kline_zip_url(sym, "1h", date)
        try:
            resp = _retryable_request(
                "GET",
                url,
                timeout=fetch.http_timeout_get_secs,
                attempts=fetch.http_retry_attempts,
            )
        except HttpStatusError as e:
            if e.status == 404:
                logger.warning("%s %s: 1h kline zip not found (404) — skipping", sym, date)
                return None
            raise
        return parse_1h_kline_zip(resp.data, sym)

    with ThreadPoolExecutor(max_workers=fetch.fetch_concurrency, thread_name_prefix="zcrypto-leadlag") as pool:
        futures = {pool.submit(_fetch_one, sym, date): (sym, date) for sym, date in work}
        try:
            for fut in as_completed(futures):
                sym, date = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    raise RuntimeError(f"{sym} {date}: fetch failed: {e}") from e
                if result is not None:
                    frames.append(result)
        except BaseException:
            for f in futures:
                f.cancel()
            raise

    if not frames:
        df = pd.DataFrame(columns=_CONTRACT_COLS)
        df["timestamp_open_utc"] = pd.Series(dtype="datetime64[ns, UTC]")
        df["symbol"] = pd.Series(dtype="object")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.Series(dtype="float64")
    else:
        df = pd.concat(frames, ignore_index=True)
        df = df.sort_values(["symbol", "timestamp_open_utc"]).reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype("float64")

    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    logger.info("cached %d rows to %s", len(df), cache)

    return df
