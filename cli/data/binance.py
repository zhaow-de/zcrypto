from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Protocol

from cli.data.config import BASE_URL, EXCHANGE_INFO_URL


class Source(Protocol):
    """Minimal interface for fetching Binance reference + kline data. Injected for tests."""

    def fetch_exchange_info(self) -> list[dict]: ...

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool: ...

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes: ...

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str: ...


def kline_zip_url(symbol: str, interval: str, date: dt.date) -> str:
    iso = date.strftime("%Y-%m-%d")
    return f"{BASE_URL}/data/spot/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{iso}.zip"


def kline_checksum_url(symbol: str, interval: str, date: dt.date) -> str:
    return kline_zip_url(symbol, interval, date) + ".CHECKSUM"


def parse_checksum_file(content: str) -> str:
    """Binance `.CHECKSUM` = `<sha256hex>  <filename>\\n` → hex (raises on malformed)."""
    head = content.strip().split(maxsplit=1)
    if not head or len(head[0]) != 64 or not all(c in "0123456789abcdefABCDEF" for c in head[0]):
        raise ValueError(f"malformed .CHECKSUM content: {content!r}")
    return head[0].lower()


class BinanceSource:
    """Concrete `Source` over stdlib `urllib.request`. HTTP paths excluded from coverage."""

    def fetch_exchange_info(self) -> list[dict]:  # pragma: no cover
        with urllib.request.urlopen(EXCHANGE_INFO_URL) as resp:
            data = json.loads(resp.read())
        return data["symbols"]

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:  # pragma: no cover
        with urllib.request.urlopen(kline_zip_url(symbol, interval, date)) as resp:
            return resp.read()

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str:  # pragma: no cover
        url = kline_checksum_url(symbol, interval, date)
        with urllib.request.urlopen(url) as resp:
            return parse_checksum_file(resp.read().decode("utf-8"))
