"""Shared, non-test helpers for cli/data tests. Imported explicitly by tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import zipfile


def synthetic_kline_csv(date: dt.date, *, base_price: float = 100.0, base_vol: float = 50.0) -> str:
    """One Binance-shaped 12-column 1d kline CSV row for the given UTC date."""
    open_ms = int(dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    close_ms = open_ms + 86_400_000 - 1
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
        f"{open_ms},{open_},{high},{low},{close},{volume},{close_ms},{quote_volume},{trades},{taker_buy_base},{taker_buy_quote},0\n"
    )


def make_zip_with_checksum(csv_text: str, inner_name: str) -> tuple[bytes, str]:
    """Pack csv_text into a zip with inner_name; return (zip_bytes, sha256_hex)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, csv_text)
    zip_bytes = buf.getvalue()
    return zip_bytes, hashlib.sha256(zip_bytes).hexdigest()


class FakeSource:
    """In-memory Source for tests; pre-load via `.add_pair` / `.add_kline`."""

    def __init__(self) -> None:
        self.exchange_info: list[dict] = []
        # (symbol, interval, date) -> (zip_bytes, sha256_hex)
        self._klines: dict[tuple[str, str, dt.date], tuple[bytes, str]] = {}

    def add_pair(self, symbol: str, base: str, quote: str) -> None:
        self.exchange_info.append({"symbol": symbol, "baseAsset": base, "quoteAsset": quote, "status": "TRADING"})

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

    # Source protocol
    def fetch_exchange_info(self) -> list[dict]:
        return list(self.exchange_info)

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:
        return (symbol, interval, date) in self._klines

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:
        return self._klines[(symbol, interval, date)][0]

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str:
        return self._klines[(symbol, interval, date)][1]


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
