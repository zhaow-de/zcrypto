from __future__ import annotations

import datetime as dt
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Protocol

from cli.constants import CliConstants
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


def _retryable_urlopen(
    req_or_url,
    *,
    timeout: float,
    attempts: int | None = None,
    base_delay: float = 1.0,
):  # pragma: no cover
    """`urlopen` with timeout + retry on transient failures.

    Retries on: TimeoutError / socket.timeout, urllib.error.URLError (non-HTTPError),
    HTTPError with 5xx code. Propagates on HTTPError with 4xx code (a 404 is a
    meaningful signal — the pair-date doesn't exist).

    `attempts` defaults to `CliConstants.HTTP_RETRY_ATTEMPTS`. Exponential backoff:
    `base_delay`, `base_delay * 2`, `base_delay * 4`, ...
    """
    if attempts is None:
        attempts = CliConstants.HTTP_RETRY_ATTEMPTS
    last_exc = None
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(req_or_url, timeout=timeout)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                raise  # client error; don't retry
            last_exc = e  # 5xx — retry
        except (TimeoutError, socket.timeout, urllib.error.URLError, OSError) as e:
            last_exc = e
        if attempt < attempts - 1:
            time.sleep(base_delay * (2**attempt))
    raise last_exc


class BinanceSource:
    """Concrete `Source` over stdlib `urllib.request`. HTTP paths excluded from coverage."""

    def fetch_exchange_info(self) -> list[dict]:  # pragma: no cover
        with _retryable_urlopen(EXCHANGE_INFO_URL, timeout=CliConstants.HTTP_TIMEOUT_GET_SECS) as resp:
            data = json.loads(resp.read())
        return data["symbols"]

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        req = urllib.request.Request(url, method="HEAD")
        try:
            with _retryable_urlopen(req, timeout=CliConstants.HTTP_TIMEOUT_HEAD_SECS):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:  # pragma: no cover
        with _retryable_urlopen(kline_zip_url(symbol, interval, date), timeout=CliConstants.HTTP_TIMEOUT_GET_SECS) as resp:
            return resp.read()

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str:  # pragma: no cover
        url = kline_checksum_url(symbol, interval, date)
        with _retryable_urlopen(url, timeout=CliConstants.HTTP_TIMEOUT_HEAD_SECS) as resp:
            return parse_checksum_file(resp.read().decode("utf-8"))
