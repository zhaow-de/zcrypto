import datetime as dt
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from cli.data.binance import _retryable_urlopen, kline_checksum_url, kline_zip_url, parse_checksum_file


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


def test_retryable_urlopen_success_first_try():
    mock_resp = MagicMock()
    with patch("cli.data.binance.urllib.request.urlopen", return_value=mock_resp) as m:
        result = _retryable_urlopen("http://x", timeout=30, attempts=3, base_delay=0.0)
    assert result is mock_resp
    assert m.call_count == 1


def test_retryable_urlopen_404_propagates_without_retry():
    err = urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
    with patch("cli.data.binance.urllib.request.urlopen", side_effect=err) as m:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _retryable_urlopen("http://x", timeout=30, attempts=3, base_delay=0.0)
    assert exc_info.value.code == 404
    assert m.call_count == 1, "404 must not be retried"


def test_retryable_urlopen_5xx_retried_then_propagates():
    err = urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, None)
    with patch("cli.data.binance.urllib.request.urlopen", side_effect=err) as m:
        with pytest.raises(urllib.error.HTTPError):
            _retryable_urlopen("http://x", timeout=30, attempts=3, base_delay=0.0)
    assert m.call_count == 3, "5xx should retry to the attempt limit"


def test_retryable_urlopen_timeout_retried_then_succeeds():
    mock_resp = MagicMock()
    side_effects = [TimeoutError(), TimeoutError(), mock_resp]
    with patch("cli.data.binance.urllib.request.urlopen", side_effect=side_effects) as m:
        result = _retryable_urlopen("http://x", timeout=30, attempts=3, base_delay=0.0)
    assert result is mock_resp
    assert m.call_count == 3


def test_retryable_urlopen_url_error_retried():
    err = urllib.error.URLError("connection refused")
    mock_resp = MagicMock()
    with patch("cli.data.binance.urllib.request.urlopen", side_effect=[err, mock_resp]) as m:
        result = _retryable_urlopen("http://x", timeout=30, attempts=3, base_delay=0.0)
    assert result is mock_resp
    assert m.call_count == 2
