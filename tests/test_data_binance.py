import datetime as dt
import socket
from unittest.mock import MagicMock, patch

import pytest
import urllib3.exceptions

from cli.config import FetchConfig
from cli.data.binance import (
    BinanceSource,
    HttpStatusError,
    _pool,
    _retryable_request,
    kline_checksum_url,
    kline_zip_url,
    metrics_url,
    parse_checksum_file,
)


def test_kline_zip_url_shape():
    url = kline_zip_url("BTCUSDT", "1d", dt.date(2024, 1, 2))
    assert url == ("https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-02.zip")


def test_kline_checksum_url_appends_suffix():
    url = kline_checksum_url("ETHUSDT", "1d", dt.date(2024, 1, 2))
    assert url == kline_zip_url("ETHUSDT", "1d", dt.date(2024, 1, 2)) + ".CHECKSUM"


def test_parse_checksum_file_valid():
    content = "a" * 64 + "  ETHUSDT-1d-2024-01-02.zip\n"
    assert parse_checksum_file(content) == "a" * 64


def test_parse_checksum_file_malformed_raises():
    with pytest.raises(ValueError, match="malformed"):
        parse_checksum_file("oops not a hash\n")
    with pytest.raises(ValueError, match="malformed"):
        parse_checksum_file("")


def test_retryable_request_success_first_try():
    mock_resp = MagicMock(status=200)
    with patch.object(_pool, "request", return_value=mock_resp) as m:
        result = _retryable_request("GET", "http://x", timeout=30, attempts=3, base_delay=0.0)
    assert result is mock_resp
    assert m.call_count == 1


def test_retryable_request_404_raises_HttpStatusError_no_retry():
    mock_resp = MagicMock(status=404)
    with patch.object(_pool, "request", return_value=mock_resp) as m:
        with pytest.raises(HttpStatusError) as exc_info:
            _retryable_request("HEAD", "http://x", timeout=30, attempts=3, base_delay=0.0)
    assert exc_info.value.status == 404
    assert m.call_count == 1, "404 must not be retried"


def test_retryable_request_5xx_retried_then_raises():
    mock_resp = MagicMock(status=503)
    with patch.object(_pool, "request", return_value=mock_resp) as m:
        with pytest.raises(HttpStatusError):
            _retryable_request("GET", "http://x", timeout=30, attempts=3, base_delay=0.0)
    assert m.call_count == 3


def test_retryable_request_timeout_retried_then_succeeds():
    mock_ok = MagicMock(status=200)
    side_effects = [
        urllib3.exceptions.TimeoutError("timeout"),
        urllib3.exceptions.TimeoutError("timeout"),
        mock_ok,
    ]
    with patch.object(_pool, "request", side_effect=side_effects) as m:
        result = _retryable_request("GET", "http://x", timeout=30, attempts=3, base_delay=0.0)
    assert result is mock_ok
    assert m.call_count == 3


def test_retryable_request_connection_error_retried():
    mock_ok = MagicMock(status=200)
    err = urllib3.exceptions.MaxRetryError(None, "http://x", reason="connection refused")
    with patch.object(_pool, "request", side_effect=[err, mock_ok]) as m:
        result = _retryable_request("GET", "http://x", timeout=30, attempts=3, base_delay=0.0)
    assert result is mock_ok
    assert m.call_count == 2


def test_metrics_url_shape():
    url = metrics_url("BTCUSDT", dt.date(2024, 1, 2))
    assert url == "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-01-02.zip"


# ---------------------------------------------------------------------------
# Stale-connection hang backstop: socket.setdefaulttimeout
# ---------------------------------------------------------------------------


def test_binance_source_sets_socket_default_timeout():
    """BinanceSource sets a process-wide socket read timeout as a backstop against stale
    keep-alive connections that would otherwise block ssl.read() indefinitely.

    The faulthandler-pinned hang: ssl.read ← http.client._read_status ← urllib3 getresponse
    ← _pool.request. urllib3's per-request timeout does NOT fire on the ssl.read() of the
    HTTP status line when a pooled connection is reused after the server silently dropped it.
    socket.setdefaulttimeout() is the backstop: it fires unconditionally and raises
    socket.timeout (OSError subclass), caught by _retryable_request's OSError branch.

    Assert that constructing BinanceSource with a given http_timeout_get_secs results in
    socket.getdefaulttimeout() returning a value >= http_timeout_get_secs (the margin
    above the configured timeout is an implementation detail, not a contract).
    """
    fetch = FetchConfig(http_timeout_get_secs=60)
    BinanceSource(fetch=fetch)
    timeout = socket.getdefaulttimeout()
    assert timeout is not None, "socket.setdefaulttimeout must be set (not None) after BinanceSource init"
    assert timeout >= fetch.http_timeout_get_secs, (
        f"socket default timeout ({timeout}s) must be >= http_timeout_get_secs ({fetch.http_timeout_get_secs}s)"
    )
