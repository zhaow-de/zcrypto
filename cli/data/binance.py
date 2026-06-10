from __future__ import annotations

import datetime as dt
import json
import time
from typing import Protocol

import urllib3
import urllib3.exceptions

from cli.constants import CliConstants
from cli.data.config import BASE_URL, EXCHANGE_INFO_URL
from cli.logging import get_logger

logger = get_logger("data.binance")

# Reused across all HTTP calls so TLS handshakes are amortized.
# num_pools=4 gives headroom (we use ~2 hosts: data.binance.vision + api.binance.com).
# maxsize=16 covers FETCH_CONCURRENCY=5 + pre-flight + headroom.
# retries=False so our `_retryable_request` retry loop owns the retry policy.
_pool = urllib3.PoolManager(num_pools=4, maxsize=16, retries=False)


class HttpStatusError(Exception):
    """Raised by `_retryable_request` for 4xx responses (not retried).
    Distinct from urllib3.exceptions.* so callers can match it specifically."""

    def __init__(self, status: int, url: str):
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} on {url}")


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


def _retryable_request(
    method: str,
    url: str,
    *,
    timeout: float,
    attempts: int | None = None,
    base_delay: float = 1.0,
):  # pragma: no cover
    """`_pool.request` with timeout + retry on transient failures.

    Retries on: urllib3 connection / timeout exceptions, 5xx responses.
    Raises HttpStatusError immediately on 4xx (a 404 is a meaningful signal —
    the pair-date doesn't exist).

    `attempts` defaults to `CliConstants.HTTP_RETRY_ATTEMPTS`. Exponential backoff:
    `base_delay`, `base_delay * 2`, `base_delay * 4`, ...
    """
    if attempts is None:
        attempts = CliConstants.HTTP_RETRY_ATTEMPTS
    last_exc = None
    for attempt in range(attempts):
        logger.debug(
            "HTTP %s %s (attempt %d/%d, timeout=%ss)",
            method,
            url,
            attempt + 1,
            attempts,
            timeout,
        )
        _start = time.monotonic()
        try:
            resp = _pool.request(method, url, timeout=timeout)
            _ms = (time.monotonic() - _start) * 1000
            if 200 <= resp.status < 300:
                logger.debug("HTTP %s %s → %d in %.0fms", method, url, resp.status, _ms)
                return resp
            if 400 <= resp.status < 500:
                logger.debug(
                    "HTTP %s %s → %d in %.0fms (4xx, propagating)",
                    method,
                    url,
                    resp.status,
                    _ms,
                )
                raise HttpStatusError(resp.status, url)
            # 5xx
            logger.debug(
                "HTTP %s %s → %d in %.0fms (5xx, will retry)",
                method,
                url,
                resp.status,
                _ms,
            )
            last_exc = HttpStatusError(resp.status, url)
        except HttpStatusError:
            raise
        except (urllib3.exceptions.HTTPError, OSError, TimeoutError) as e:
            _ms = (time.monotonic() - _start) * 1000
            logger.debug(
                "HTTP %s %s → %s in %.0fms (will retry)",
                method,
                url,
                type(e).__name__,
                _ms,
            )
            last_exc = e
        if attempt < attempts - 1:
            _delay = base_delay * (2**attempt)
            logger.debug("retrying %s %s in %.1fs", method, url, _delay)
            time.sleep(_delay)
    raise last_exc


class BinanceSource:
    """Concrete `Source` over urllib3 PoolManager. HTTP paths excluded from coverage."""

    def fetch_exchange_info(self) -> list[dict]:  # pragma: no cover
        resp = _retryable_request("GET", EXCHANGE_INFO_URL, timeout=CliConstants.HTTP_TIMEOUT_GET_SECS)
        data = json.loads(resp.data)
        return data["symbols"]

    def exists_kline(self, symbol: str, interval: str, date: dt.date) -> bool:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        try:
            _retryable_request("HEAD", url, timeout=CliConstants.HTTP_TIMEOUT_HEAD_SECS)
            return True
        except HttpStatusError as e:
            if e.status == 404:
                return False
            raise

    def fetch_kline_zip(self, symbol: str, interval: str, date: dt.date) -> bytes:  # pragma: no cover
        url = kline_zip_url(symbol, interval, date)
        resp = _retryable_request("GET", url, timeout=CliConstants.HTTP_TIMEOUT_GET_SECS)
        return resp.data

    def fetch_kline_checksum(self, symbol: str, interval: str, date: dt.date) -> str:  # pragma: no cover
        url = kline_checksum_url(symbol, interval, date)
        resp = _retryable_request("GET", url, timeout=CliConstants.HTTP_TIMEOUT_HEAD_SECS)
        return parse_checksum_file(resp.data.decode("utf-8"))
