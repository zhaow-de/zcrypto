"""Shared, non-test helpers for cli/data tests. Imported explicitly by tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile


def synthetic_funding_zip(perp: str, year: int, month: int) -> bytes:
    """One Binance-shaped funding-rate CSV (header + 3 rows at 00/08/16 UTC on day 1) packed as a zip.

    Matches the schema verified against data.binance.vision:
    calc_time, funding_interval_hours, last_funding_rate (header present).
    """
    day1 = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    base_ms = int(day1.timestamp() * 1000)
    rows = [
        (base_ms + 0 * 8 * 3600 * 1000, 8, "0.00010000"),
        (base_ms + 1 * 8 * 3600 * 1000, 8, "0.00020000"),
        (base_ms + 2 * 8 * 3600 * 1000, 8, "0.00030000"),
    ]
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    lines += [f"{ct},{iv},{rate}" for ct, iv, rate in rows]
    csv = ("\n".join(lines) + "\n").encode()
    inner_name = f"{perp}-fundingRate-{year}-{month:02d}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv)
    return buf.getvalue()


def synthetic_metrics_zip(perp: str, date: dt.date) -> bytes:
    """Synthetic Binance daily metrics zip (one row — last-of-day snapshot).

    Uses uniform default values; callers only need the fields to be present and non-NaN.
    """
    header = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
    )
    ts = f"{date} 23:55:00"
    row = f"{ts},{perp},80000.0,3500000000.0,1.1,1.2,1.1,1.0\n"
    csv_text = header + row
    inner = f"{perp}-metrics-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner, csv_text)
    return buf.getvalue()


def synthetic_basis_zip(perp: str, date: dt.date) -> bytes:
    """Synthetic Binance daily premiumIndexKlines zip (one 1d candle row).

    Uses a small positive basis value; callers only need the field to be present and non-NaN.
    """
    header = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
    open_ms = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp()) * 1000
    close_ms = open_ms + 86400000 - 1
    row = f"{open_ms},0.0007,0.001,-0.0001,0.0007,0,{close_ms},0,100,0,0,0\n"
    csv_text = header + row
    inner = f"{perp}-1d-{date}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner, csv_text)
    return buf.getvalue()


def synthetic_kline_csv(date: dt.date, *, base_price: float = 100.0, base_vol: float = 50.0, precision: str = "ms") -> str:
    """One Binance-shaped 12-column 1d kline CSV row for the given UTC date.

    `precision` selects the open_time/close_time unit, matching Binance's archive
    history: "ms" (milliseconds, before 2025-01-01) or "us" (microseconds, from
    2025-01-01 onward — see binance-public-data README)."""
    epoch_s = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp())
    if precision == "ms":
        open_t = epoch_s * 1_000
        close_t = open_t + 86_400_000 - 1
    elif precision == "us":
        open_t = epoch_s * 1_000_000
        close_t = open_t + 86_400_000_000 - 1
    else:
        raise ValueError(f"unknown precision {precision!r}")
    open_ = base_price
    close = base_price * 1.01
    high = close * 1.02
    low = open_ * 0.98
    volume = base_vol
    quote_volume = volume * (open_ + close) / 2.0
    trades = 100
    taker_buy_base = volume * 0.5
    taker_buy_quote = quote_volume * 0.5
    return (
        f"{open_t},{open_},{high},{low},{close},{volume},{close_t},{quote_volume},{trades},{taker_buy_base},{taker_buy_quote},0\n"
    )


def make_zip_with_checksum(csv_text: str, inner_name: str) -> tuple[bytes, str]:
    """Pack csv_text into a zip with inner_name; return (zip_bytes, sha256_hex)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    zip_bytes = buf.getvalue()
    return zip_bytes, hashlib.sha256(zip_bytes).hexdigest()


class FakeSource:
    """In-memory Source for tests; pre-load via `.add_pair` / `.add_kline` / `.add_funding`."""

    def __init__(self) -> None:
        self.exchange_info: list[dict] = []
        # (symbol, interval, date) -> (zip_bytes, sha256_hex)
        self._klines: dict[tuple[str, str, dt.date], tuple[bytes, str]] = {}
        # (symbol, interval, date) entries with no published .CHECKSUM
        self._no_checksum: set[tuple[str, str, dt.date]] = set()
        # (perp, year, month) -> zip_bytes
        self._funding: dict[tuple[str, int, int], bytes] = {}
        # (symbol, date) -> zip_bytes
        self._aggtrades: dict[tuple[str, dt.date], bytes] = {}
        # (symbol, date) -> sha256_hex, only for entries registered with a checksum
        self._aggtrades_checksum: dict[tuple[str, dt.date], str] = {}
        # (perp, date) -> zip_bytes for daily metrics archives
        self._metrics: dict[tuple[str, dt.date], bytes] = {}
        # (perp, date) -> zip_bytes for daily basis (premiumIndexKlines) archives
        self._basis: dict[tuple[str, dt.date], bytes] = {}

    def add_pair(self, symbol: str, base: str, quote: str, status: str = "TRADING") -> None:
        self.exchange_info.append({"symbol": symbol, "baseAsset": base, "quoteAsset": quote, "status": status})

    def add_kline(
        self,
        symbol: str,
        interval: str,
        date: dt.date,
        *,
        base_price: float = 100.0,
        base_vol: float = 50.0,
    ) -> None:
        csv = synthetic_kline_csv(date, base_price=base_price, base_vol=base_vol)
        zip_bytes, digest = make_zip_with_checksum(csv, f"{symbol}-{interval}-{date}.csv")
        self._klines[(symbol, interval, date)] = (zip_bytes, digest)

    def tamper_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> None:
        """Force a checksum mismatch on the next fetch (for negative-path tests)."""
        zb, _ = self._klines[(symbol, interval, date)]
        self._klines[(symbol, interval, date)] = (zb, "0" * 64)

    def drop_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> None:
        """Simulate a published zip with no sibling `.CHECKSUM` (fetch returns None)."""
        self._no_checksum.add((symbol, interval, date))

    def add_aggtrades(self, symbol: str, date: dt.date, *, raw: bytes, checksum: str | None = None) -> None:
        """Register raw zip bytes for (symbol, date) aggTrades.

        Pass `checksum` (sha256 hex) to also register a published `.CHECKSUM`, so
        `fetch_aggtrades_checksum` returns it (the sha256-validated path). Omit it
        (default) to leave the entry unchecksummed (`fetch_aggtrades_checksum` → None)."""
        self._aggtrades[(symbol, date)] = raw
        if checksum is not None:
            self._aggtrades_checksum[(symbol, date)] = checksum

    def add_funding(self, perp: str, year: int, month: int, *, raw: bytes | None = None) -> None:
        """Register a synthetic monthly funding archive for `perp` / `year-month`.

        If `raw` is omitted, `synthetic_funding_zip` is used to generate 3 rows (00/08/16 UTC on day 1).
        Pass `raw` to supply custom bytes (must be parseable by `funding.parse_funding`).
        """
        self._funding[(perp, year, month)] = raw if raw is not None else synthetic_funding_zip(perp, year, month)

    def add_metrics(self, perp: str, date: dt.date, *, raw: bytes | None = None) -> None:
        """Register a synthetic daily metrics archive for `perp` / `date`.

        If `raw` is omitted, `synthetic_metrics_zip` is used (one last-of-day row with default values).
        """
        self._metrics[(perp, date)] = raw if raw is not None else synthetic_metrics_zip(perp, date)

    def add_basis(self, perp: str, date: dt.date, *, raw: bytes | None = None) -> None:
        """Register a synthetic daily basis (premiumIndexKlines) archive for `perp` / `date`.

        If `raw` is omitted, `synthetic_basis_zip` is used (one 1d candle with a small positive basis).
        """
        self._basis[(perp, date)] = raw if raw is not None else synthetic_basis_zip(perp, date)

    # Source protocol
    def fetch_exchange_info(self) -> list[dict]:
        return list(self.exchange_info)

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:
        return (symbol, interval, date) in self._klines

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:
        return self._klines[(symbol, interval, date)][0]

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str | None:
        if (symbol, interval, date) in self._no_checksum:
            return None
        return self._klines[(symbol, interval, date)][1]

    def fetch_funding_archive(self, perp: str, year: int, month: int) -> bytes | None:
        return self._funding.get((perp, year, month))

    def fetch_metrics_archive(self, perp: str, date: dt.date) -> bytes | None:
        return self._metrics.get((perp, date))

    def fetch_basis_archive(self, perp: str, date: dt.date) -> bytes | None:
        return self._basis.get((perp, date))

    def fetch_aggtrades_archive(self, symbol: str, date: dt.date) -> bytes:
        return self._aggtrades[(symbol, date)]

    def fetch_aggtrades_checksum(self, symbol: str, date: dt.date) -> str | None:
        return self._aggtrades_checksum.get((symbol, date))


import threading
import time


class CountingSource(FakeSource):
    """FakeSource that tracks peak concurrent in-flight `fetch_kline_zip` calls."""

    def __init__(self, *, request_delay: float = 0.02) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._active = 0
        self._delay = request_delay
        self.peak_concurrent = 0
        self.total_requests = 0

    def fetch_kline_zip(self, symbol: str, interval: str, date) -> bytes:
        with self._lock:
            self._active += 1
            self.total_requests += 1
            if self._active > self.peak_concurrent:
                self.peak_concurrent = self._active
        try:
            time.sleep(self._delay)  # give other threads a window to enter
            return super().fetch_kline_zip(symbol, interval, date)
        finally:
            with self._lock:
                self._active -= 1
